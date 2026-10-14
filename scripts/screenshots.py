"""Take phone-sized screenshots of a running instance seeded with demo data.

    python -m app.seed --users        # in the container / dev env
    pip install playwright && playwright install chromium
    python scripts/screenshots.py http://localhost:8080 demo demo-password

Also checks every view for horizontal overflow and JavaScript errors at 360, 390 and 430 px widths.
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent.parent / "docs" / "screenshots"
VIEWS = ["feed", "item", "reels", "sources", "discover", "past", "admin", "menu"]
SIZES = [(360, 640), (390, 844), (430, 932)]


def main(base: str, user: str, password: str, shots: bool = True) -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    problems: list[str] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for w, hgt in SIZES:
            ctx = browser.new_context(
                viewport={"width": w, "height": hgt}, device_scale_factor=2, is_mobile=True, has_touch=True,
                color_scheme="dark",
            )  # fmt: skip
            page = ctx.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e, errors=errors: errors.append(str(e)))
            page.on("console", lambda m, errors=errors: errors.append(m.text) if m.type == "error" else None)
            page.goto(base + "/#/feed")
            page.wait_for_selector("form, .card")
            if page.locator("#f-user").count():
                page.fill("#f-user", user)
                page.fill("#f-pw", password)
                page.click("button[type=submit]")
            page.wait_for_selector(".card:not(.skeleton)")
            for view in VIEWS:
                if view == "item":
                    page.goto(base + "/#/feed")
                    page.wait_for_selector(".card:not(.skeleton) .card-body")
                    page.locator(".card:not(.skeleton) .card-body").first.click()
                    page.wait_for_selector(".prose")
                elif view == "menu":
                    page.goto(base + "/#/feed")
                    page.wait_for_selector(".card:not(.skeleton)")
                    page.click("#menu-btn")
                    page.wait_for_selector(".sheet")
                else:
                    page.goto(base + f"/#/{view}")
                    page.wait_for_timeout(300)
                    sel = {"reels": ".slide", "sources": ".src-card", "discover": ".disc-item", "past": ".past",
                           "admin": ".kv", "feed": ".card:not(.skeleton)"}[view]  # fmt: skip
                    page.wait_for_selector(sel, timeout=15000)
                page.wait_for_timeout(700)
                overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                if overflow > 0:
                    problems.append(f"{w}px {view}: horizontal overflow {overflow}px")
                small = page.evaluate(
                    """[...document.querySelectorAll('button, a.btn, a.act, .tab')].filter(e => {
                        const r = e.getBoundingClientRect(); return r.width && r.height && e.offsetParent !== null
                        && (r.height < 32 || r.width < 32); }).map(e => e.className + ':' + (e.textContent||'').trim().slice(0,20))"""
                )
                if small:
                    problems.append(f"{w}px {view}: small targets {small[:5]}")
                if shots and w == 390:
                    # Playwright's Chromium build has no H.264 decoder, so hide the "cannot play" note.
                    page.add_style_tag(content=".slide .err { display: none !important; }")
                    page.screenshot(path=str(OUT / f"{view}.png"))
            if errors:
                problems.append(f"{w}px JS errors: {errors[:5]}")
            ctx.close()
        browser.close()
    for pr in problems:
        print("PROBLEM:", pr)
    print("screenshots in", OUT)
    return 1 if problems else 0


if __name__ == "__main__":
    args = sys.argv[1:] + [None] * 3
    sys.exit(main(args[0] or "http://localhost:8080", args[1] or "demo", args[2] or "demo-password"))
