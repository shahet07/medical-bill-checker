// Downloads the hero background video into public/media/ before a build.
//
// The clip is "Woman completing paperwork with a calculator" from Mixkit
// (https://mixkit.co/free-stock-video/woman-completing-paperwork-with-a-calculator-46505/),
// under the Mixkit Stock Video Free License: free to use in a project like
// this site, but the raw file may not be redistributed, so it is not
// committed to git (public/media/ is ignored). If the download fails the
// build still succeeds and the hero shows its plain gradient instead.
import { existsSync, mkdirSync, statSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "public", "media");
const BASE = "https://assets.mixkit.co/videos/46505/46505";
const FILES = {
  "hero-720.mp4": `${BASE}-720.mp4`,
  "hero-360.mp4": `${BASE}-360.mp4`,
  "hero-poster.jpg": `${BASE}-thumb-720-0.jpg`,
};

mkdirSync(OUT, { recursive: true });
for (const [name, url] of Object.entries(FILES)) {
  const path = join(OUT, name);
  if (existsSync(path) && statSync(path).size > 0) continue;
  try {
    const resp = await fetch(url, { headers: { "User-Agent": "clyvexa-build" } });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    writeFileSync(path, Buffer.from(await resp.arrayBuffer()));
    console.log("fetched", name);
  } catch (err) {
    console.warn(`warning: could not fetch ${name} (${err.message}); the hero will use its gradient`);
  }
}
