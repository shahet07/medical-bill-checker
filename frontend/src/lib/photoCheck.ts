// Check a photo on the user's device, before anything is uploaded.
// Same preprocessing as billchecker/photo_quality.py: grayscale, the whole page
// letterboxed to 192px, and the highest-contrast 192px tile at 1024px scale.

import { Manifest, SIZE, buildModel, loadWeights, logits } from "./photoModel";

const DETAIL_EDGE = 1024;
const STRIDE = 96;
const BASE = "/models/photo-quality/";

export interface DeviceCheck {
  issues: string[];
  scores: Record<string, number>;
}

let loading: Promise<{ tf: unknown; model: unknown; manifest: Manifest }> | null = null;

function load() {
  loading ??= (async () => {
    const tf = await import("@tensorflow/tfjs"); // fetched only when someone picks a photo
    const [manifest, weights] = await Promise.all([
      fetch(BASE + "manifest.json").then((r) => r.json() as Promise<Manifest>),
      fetch(BASE + "weights.bin").then((r) => r.arrayBuffer()),
    ]);
    const model = buildModel(tf, manifest);
    loadWeights(tf, model, manifest, weights);
    return { tf, model, manifest };
  })();
  loading.catch(() => (loading = null));
  return loading;
}

function grayCanvas(src: CanvasImageSource, w: number, h: number): Uint8ClampedArray {
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d", { willReadFrequently: true })!;
  ctx.imageSmoothingQuality = "high";
  ctx.drawImage(src, 0, 0, w, h);
  const rgba = ctx.getImageData(0, 0, w, h).data;
  const gray = new Uint8ClampedArray(w * h);
  for (let i = 0; i < gray.length; i++) gray[i] = (rgba[4 * i] * 299 + rgba[4 * i + 1] * 587 + rgba[4 * i + 2] * 114) / 1000;
  return gray;
}

function fit(w: number, h: number, edge: number): [number, number] {
  const s = Math.min(edge / w, edge / h, 1); // like PIL thumbnail: only shrink
  return [Math.max(1, Math.round(w * s)), Math.max(1, Math.round(h * s))];
}

function letterbox(src: CanvasImageSource, w: number, h: number): Uint8ClampedArray {
  const [tw, th] = fit(w, h, SIZE);
  const small = grayCanvas(src, tw, th);
  const out = new Uint8ClampedArray(SIZE * SIZE);
  const ox = Math.floor((SIZE - tw) / 2);
  const oy = Math.floor((SIZE - th) / 2);
  for (let y = 0; y < th; y++) out.set(small.subarray(y * tw, y * tw + tw), (y + oy) * SIZE + ox);
  return out;
}

function detailTile(src: CanvasImageSource, w: number, h: number): Uint8ClampedArray {
  const [dw, dh] = fit(w, h, DETAIL_EDGE);
  if (dw < SIZE || dh < SIZE) return letterbox(src, w, h);
  const g = grayCanvas(src, dw, dh);
  let best = -1;
  let bx = 0;
  let by = 0;
  for (let y = 0; y + SIZE <= dh; y += STRIDE) {
    for (let x = 0; x + SIZE <= dw; x += STRIDE) {
      let sum = 0;
      let sq = 0;
      for (let yy = y; yy < y + SIZE; yy++) {
        for (let xx = x; xx < x + SIZE; xx++) {
          const v = g[yy * dw + xx];
          sum += v;
          sq += v * v;
        }
      }
      const n = SIZE * SIZE;
      const std = Math.sqrt(Math.max(sq / n - (sum / n) ** 2, 0));
      if (std > best) [best, bx, by] = [std, x, y];
    }
  }
  const tile = new Uint8ClampedArray(SIZE * SIZE);
  for (let y = 0; y < SIZE; y++) tile.set(g.subarray((by + y) * dw + bx, (by + y) * dw + bx + SIZE), y * SIZE);
  return tile;
}

/** null when the browser can't read the file as an image (e.g. HEIC, PDF): the server checks those. */
export async function checkPhoto(file: File): Promise<DeviceCheck | null> {
  if (!/^image\/(jpeg|png|webp)$/.test(file.type)) return null;
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: "from-image" });
  } catch {
    return null;
  }
  const whole = letterbox(bitmap, bitmap.width, bitmap.height);
  const detail = detailTile(bitmap, bitmap.width, bitmap.height);
  bitmap.close();
  const pixels = new Uint8ClampedArray(SIZE * SIZE * 2);
  for (let i = 0; i < SIZE * SIZE; i++) {
    pixels[2 * i] = whole[i];
    pixels[2 * i + 1] = detail[i];
  }
  const { tf, model, manifest } = await load();
  const z = logits(tf, model, pixels);
  const scores: Record<string, number> = {};
  const issues: string[] = [];
  manifest.labels.forEach((label, i) => {
    scores[label] = 1 / (1 + Math.exp(-z[i]));
    if (scores[label] >= (manifest.thresholds[label] ?? 0.5)) issues.push(label);
  });
  return { issues, scores };
}
