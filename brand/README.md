# Brand: Clyvexa

| File | Use |
|---|---|
| `mark.svg` | The logo mark (rounded square). Source for the web icons |
| `mark-maskable.svg` | Full-bleed version with the art inside Android's safe zone |
| `lockup.svg` / `lockup.png` | Clyvexa wordmark with "Medical bill checker" and what it does, for documents and the store listing |
| `play-store-icon-512.png` | Google Play icon: 512×512, full-bleed (Play applies the rounded mask) |
| `preview.png` | The icon at real sizes, on light and dark, with Android masks |

Colors: blue `#2b6fd6` → `#1a4fa3`, check green `#3ed08a`, flagged line `#e8a33a` on `#fde7b3`, bill lines `#c7d8f3`, wordmark `#16233a`.

The concept: the **C** of Clyvexa, drawn as a magnifying glass (the app inspects your bill). Under the lens are bill lines, one highlighted (a mistake it found), and a green check (the bill was checked). Tagline: "Finds the mistakes in your bill. Writes the letter."

After editing an SVG, regenerate the PNGs (web icons go to `frontend/public/`):

    .venv/bin/python brand/render.py
