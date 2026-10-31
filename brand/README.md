# Brand: Clyvexa

| File | Use |
|---|---|
| `mark.svg` | The logo mark (rounded square). Source for the web icons |
| `mark-maskable.svg` | Full-bleed version with the art inside Android's safe zone |
| `lockup.svg` / `lockup.png` | Clyvexa wordmark with "Medical bill checker", for documents and the store listing |
| `play-store-icon-512.png` | Google Play icon: 512×512, full-bleed (Play applies the rounded mask) |
| `preview.png` | The icon at real sizes, on light and dark, with Android masks |

Colors: blue `#2b6fd6` → `#1a4fa3`, check green `#1f9d5c`, flagged line `#e8a33a` on `#fde7b3`, page lines `#c7d8f3`.

The concept: a bill with one highlighted line (a problem the app found) and a green check (the bill was checked).

After editing an SVG, regenerate the PNGs (web icons go to `frontend/public/`):

    .venv/bin/python brand/render.py
