"""Internal HTTP transport. All response payloads stay in anonymous process pipes."""
import json
import sys
from urllib.parse import urlparse
from curl_cffi import requests

request = json.load(sys.stdin)
try:
    url = request["url"]
    with requests.Session(impersonate="chrome") as session:
        if request.get("form"):
            response = session.post(url, data=request["form"], timeout=120)
        else:
            response = session.get(url, timeout=120)
    if urlparse(url).hostname == "www.dallascountyvotes.org" and response.status_code in (202, 403):
        # The county requires a JavaScript challenge before downloads. No profile is saved.
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
            try:
                context = browser.new_context()
                page = context.new_page()
                year = "2024" if "/2024/" in url or "2024-general" in url else "2026"
                landing = "https://www.dallascountyvotes.org/election-results/historical/" + (
                    "november-5-2024-general-joint-election/" if year == "2024" else "november-3-2026-general-and-joint-election/"
                )
                page.goto(landing, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(10000)
                if "/historical/" in url:
                    payload = page.content().encode()
                else:
                    downloaded = context.request.get(url, timeout=120000)
                    if not downloaded.ok:
                        raise RuntimeError("county browser download failed")
                    payload = downloaded.body()
                sys.stdout.buffer.write(payload)
            finally:
                browser.close()
    else:
        response.raise_for_status()
        if response.status_code == 202:
            raise RuntimeError("official source not ready")
        sys.stdout.buffer.write(response.content)
except Exception as error:
    # Do not echo response bodies or voter identifiers.
    print(f"Official download failed ({type(error).__name__})", file=sys.stderr)
    sys.exit(1)
