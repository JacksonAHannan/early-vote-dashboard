"""Internal HTTP transport. All response payloads stay in anonymous process pipes."""
import json
import sys
from time import sleep
from urllib.parse import urlparse

GEORGIA_PUBLIC_HOST = 'd11khjvhu86vzz.cloudfront.net'


def needs_browser(url, status):
    host = urlparse(url).hostname
    return (host == 'www.dallascountyvotes.org' and status in (202, 403)
            or host == GEORGIA_PUBLIC_HOST and status == 403)


def browser_download(url, headers):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path='/usr/bin/chromium', headless=True)
        try:
            context = browser.new_context(extra_http_headers=headers or {})
            page = context.new_page()
            if urlparse(url).hostname == 'www.dallascountyvotes.org':
                # The county requires a normal browser before public downloads.
                year = '2024' if '/2024/' in url or '2024-general' in url else '2026'
                landing = 'https://www.dallascountyvotes.org/election-results/historical/' + (
                    'november-5-2024-general-joint-election/' if year == '2024' else 'november-3-2026-general-and-joint-election/'
                )
                page.goto(landing, wait_until='domcontentloaded', timeout=60000)
                page.wait_for_timeout(10000)
                if '/historical/' in url:
                    return page.content().encode()
                downloaded = context.request.get(url, timeout=120000)
            else:
                # Only the official Georgia public host is allowed here. The
                # browser visits the same public endpoint, without a proxy/profile.
                downloaded = page.goto(url, wait_until='domcontentloaded', timeout=60000)
            if downloaded is None or not downloaded.ok:
                raise RuntimeError('public browser download failed')
            return downloaded.body()
        finally:
            browser.close()


def download(request):
    from curl_cffi import requests
    url, headers = request['url'], request.get('headers')
    with requests.Session(impersonate='chrome') as session:
        for attempt in range(2):
            try:
                if request.get('form'):
                    response = session.post(url, data=request['form'], headers=headers, timeout=120)
                else:
                    response = session.get(url, headers=headers, timeout=120)
            except requests.RequestsError:
                # curl eagerly reads the complete response. A timeout/partial body
                # must retry the same request, never return its incomplete bytes.
                if attempt:
                    raise
                sleep(0.5)
                continue
            if needs_browser(url, response.status_code):
                return browser_download(url, headers)
            if not attempt and (response.status_code == 429 or response.status_code >= 500):
                sleep(0.5)
                continue
            response.raise_for_status()
            if response.status_code == 202:
                raise RuntimeError('official source not ready')
            return response.content


def main():
    try:
        request = json.load(sys.stdin)
        sys.stdout.buffer.write(download(request))
        return 0
    except Exception as error:
        # Do not echo response bodies, request credentials or voter identifiers.
        print(f'Official download failed ({type(error).__name__})', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
