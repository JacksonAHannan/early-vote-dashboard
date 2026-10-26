"""Exercise the real support form, responsive header and anonymous PayPal checkout.

TURNOUT_TEST_URL=http://127.0.0.1:8743 uv run --with playwright python dashboard/tests/support_button.py
No amount is entered and no Continue, login or payment action is taken.
"""
import json
import os
import traceback
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("TURNOUT_TEST_URL", "http://127.0.0.1:8743").rstrip("/") + "/"
OUT = ROOT / "analysis/support-link" / os.environ.get("TURNOUT_TEST_TAG", "local")
OUT.mkdir(parents=True, exist_ok=True)
REPORT = {"url": BASE, "checks": [], "javascript_errors": [], "passed": False}
EXPECTED = {"cmd": ["_xclick"], "business": ["jacksonahannan@outlook.com"],
            "item_name": ["Buy me a coffee"], "currency_code": ["USD"], "no_shipping": ["1"]}


def checkout(page, context, tag, keyboard=False):
    posts = []

    def capture(request):
        if request.method == "POST" and request.url == "https://www.paypal.com/cgi-bin/webscr":
            posts.append(parse_qs(request.post_data or ""))

    context.on("request", capture)
    try:
        button = page.locator("#support-link")
        with page.expect_popup(timeout=30000) as opened:
            if keyboard:
                button.focus()
                expect(button).to_be_focused()
                button.press("Enter")
            else:
                button.click()
        popup = opened.value
        expect(popup.locator("#itemPrice")).to_be_visible(timeout=60000)
        expect(popup.locator("#itemPrice")).to_have_value("")
        expect(popup.locator("#itemName")).to_have_value("Buy me a coffee")
        expect(popup.locator("body")).to_contain_text("Jackson Hannan")
        expect(popup.locator("body")).to_contain_text("USD")
        assert "donat" not in urlsplit(popup.url).path.lower()
        assert posts == [EXPECTED], posts
        popup.screenshot(path=str(OUT / f"checkout-{tag}.png"), full_page=True)
        REPORT["checks"].append({"checkout": tag, "path": urlsplit(popup.url).path,
                                 "recipient": "Jackson Hannan", "custom_amount_blank": True})
        popup.close()
    finally:
        context.remove_listener("request", capture)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/usr/bin/chromium", headless=True)
        try:
            for width in [1512, 390]:
                context = browser.new_context(viewport={"width": width, "height": 1000}, reduced_motion="reduce")
                page = context.new_page()
                page.on("pageerror", lambda error: REPORT["javascript_errors"].append(str(error)))
                page.goto(BASE, wait_until="networkidle", timeout=120000)
                form = page.locator("form.support-form")
                expect(form).to_be_visible()
                assert form.get_attribute("action") == "https://www.paypal.com/cgi-bin/webscr"
                assert form.get_attribute("method").lower() == "post"
                assert form.get_attribute("target") == "_blank"
                assert "noopener" in form.get_attribute("rel").split()
                assert form.locator('input[name="amount"]').count() == 0
                for state in ["tx", "ga", "nc", "va", "nv"]:
                    page.locator("#state-select").select_option(state)
                    expect(page.locator("#support-link")).to_be_visible()
                    layout = page.evaluate("""()=>{const a=document.querySelector('#support-link').getBoundingClientRect(),
                        b=document.querySelector('#refresh').getBoundingClientRect();return {
                        overflow:document.documentElement.scrollWidth>innerWidth,
                        inside:a.left>=0&&a.right<=innerWidth,
                        overlap:a.left<b.right&&a.right>b.left&&a.top<b.bottom&&a.bottom>b.top};}""")
                    assert layout == {"overflow": False, "inside": True, "overlap": False}, (state, width, layout)
                if width == 390:
                    page.locator("#state-select").select_option("tx")
                    expect(page.locator("#days")).to_be_visible()
                    # Exercise the full twelve-day strip even with an older data fixture.
                    strip = page.evaluate("""()=>{const d=document.querySelector('#days'),saved=[...d.children];
                        try{d.replaceChildren(...Array.from({length:12},(_,i)=>{const b=document.createElement('button');b.textContent='Day '+(i+1);return b;}));
                        const overflow=document.documentElement.scrollWidth>innerWidth,scroll=d.scrollWidth>d.clientWidth;
                        d.scrollLeft=d.scrollWidth;const last=d.lastElementChild.getBoundingClientRect();
                        return {overflow,scroll,lastVisible:last.right<=innerWidth};}
                        finally{d.replaceChildren(...saved);d.scrollLeft=0;}}""")
                    assert strip == {"overflow": False, "scroll": True, "lastVisible": True}, strip
                page.locator("#support-link").focus()
                page.locator("header").screenshot(path=str(OUT / f"header-{width}.png"))
                checkout(page, context, str(width), keyboard=width == 1512)
                context.close()
            # Native form submission also works when dashboard JavaScript is unavailable.
            context = browser.new_context(viewport={"width": 1280, "height": 900})
            page = context.new_page()
            page.route("**/*.js", lambda route: route.abort())
            page.goto(BASE, wait_until="domcontentloaded", timeout=120000)
            checkout(page, context, "no-dashboard-js")
            context.close()
            assert not REPORT["javascript_errors"], REPORT["javascript_errors"]
            REPORT["checks"].append("All five state headers fit desktop/mobile; keyboard and native form checkout work")
            REPORT["passed"] = True
        finally:
            browser.close()


if __name__ == "__main__":
    try:
        main()
    except BaseException:
        REPORT["failure"] = traceback.format_exc()
        raise
    finally:
        (OUT / "verification.json").write_text(json.dumps(REPORT, indent=2) + "\n")
        print(json.dumps({k: v for k, v in REPORT.items() if k != "failure"}))
