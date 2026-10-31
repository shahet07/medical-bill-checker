// Proves the TensorFlow.js model computes what the Keras model computed:
// loads the browser's own photoModel.ts (Node strips its types), runs the saved
// reference inputs, and compares logits with Keras's.
//   node scripts/tfjs-parity.mjs [tolerance]
import { readFileSync } from "node:fs";
import * as tf from "@tensorflow/tfjs";
import { buildModel, loadWeights, logits } from "../src/lib/photoModel.ts";

const tolerance = Number(process.argv[2] ?? 1e-3);
const dir = new URL("../public/models/photo-quality/", import.meta.url);
const manifest = JSON.parse(readFileSync(new URL("manifest.json", dir), "utf8"));
const bin = readFileSync(new URL("weights.bin", dir));
const parity = JSON.parse(readFileSync(new URL("../../tests/data/tfjs_parity.json", import.meta.url), "utf8"));

await tf.setBackend("cpu");
const model = buildModel(tf, manifest);
loadWeights(tf, model, manifest, bin.buffer.slice(bin.byteOffset, bin.byteOffset + bin.byteLength));

let worst = 0;
parity.inputs.forEach((pixels, i) => {
  const got = logits(tf, model, pixels);
  got.forEach((v, j) => (worst = Math.max(worst, Math.abs(v - parity.logits[i][j]))));
});
console.log(JSON.stringify({ samples: parity.inputs.length, max_abs_diff: worst, tolerance }));
process.exit(worst <= tolerance ? 0 : 1);
