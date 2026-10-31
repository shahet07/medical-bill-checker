"""Render the logo SVGs to every PNG the web app and the Play Store need (uses Chrome via Playwright).

    .venv/bin/python brand/render.py
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

BRAND = Path(__file__).resolve().parent
PUBLIC = BRAND.parent / "frontend" / "public"

OUTPUTS = [
    # (source, size, output, transparent background)
    ("mark.svg", 512, PUBLIC / "icon-512.png", True),
    ("mark.svg", 192, PUBLIC / "icon-192.png", True),
    ("mark.svg", 180, PUBLIC / "apple-touch-icon.png", False),
    ("mark.svg", 48, PUBLIC / "favicon-48.png", True),
    ("mark.svg", 32, PUBLIC / "favicon-32.png", True),
    ("mark-maskable.svg", 512, PUBLIC / "icon-maskable-512.png", False),
    ("mark-maskable.svg", 512, BRAND / "play-store-icon-512.png", False),  # Play: 512x512, full-bleed, Play applies the mask
]


def main() -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        for src, size, out, transparent in OUTPUTS:
            page = browser.new_page(viewport={"width": size, "height": size})
            svg = (BRAND / src).read_text()
            page.set_content('<html><body style="margin:0;background:transparent">' + svg.replace("<svg ", '<svg width="{0}" height="{0}" '.format(size), 1) + "</body></html>")
            out.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out), omit_background=transparent, clip={"x": 0, "y": 0, "width": size, "height": size})
            page.close()
            print("wrote", out.relative_to(BRAND.parent))
        # Lockup (wordmark) at 2x.
        page = browser.new_page(viewport={"width": 1240, "height": 300}, device_scale_factor=2)
        page.set_content('<html><body style="margin:0;background:transparent">' + (BRAND / "lockup.svg").read_text().replace("<svg ", '<svg width="1240" height="300" ', 1) + "</body></html>")
        page.screenshot(path=str(BRAND / "lockup.png"), omit_background=True)
        print("wrote brand/lockup.png")
        browser.close()


if __name__ == "__main__":
    main()
