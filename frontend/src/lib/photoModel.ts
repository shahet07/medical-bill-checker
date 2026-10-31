// The in-browser photo quality network (TensorFlow.js), rebuilt from the
// Keras model trained by scripts/train_photo_quality_tf.py. Pure functions
// with `tf` passed in, so the same file runs in the browser and in a Node
// parity test against Keras.

export const SIZE = 192;

export interface WeightEntry {
  layer: string;
  name: string;
  shape: number[];
  offset: number;
}

export interface Manifest {
  version: number;
  labels: string[];
  architecture: { filters: number[]; kernel: number; batchnorm_epsilon: number; dense: number };
  weights: WeightEntry[];
  thresholds: Record<string, number>;
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type TF = any;

export function buildModel(tf: TF, m: Manifest) {
  const model = tf.sequential();
  m.architecture.filters.forEach((filters: number, i: number) => {
    model.add(
      tf.layers.conv2d({
        ...(i === 0 ? { inputShape: [SIZE, SIZE, 2] } : {}),
        filters,
        kernelSize: m.architecture.kernel,
        padding: "same",
        useBias: false,
      }),
    );
    model.add(tf.layers.batchNormalization({ epsilon: m.architecture.batchnorm_epsilon }));
    model.add(tf.layers.reLU());
    model.add(tf.layers.maxPooling2d({ poolSize: 2 }));
  });
  model.add(tf.layers.globalAveragePooling2d({}));
  model.add(tf.layers.dropout({ rate: 0.2 }));
  model.add(tf.layers.dense({ units: m.architecture.dense }));
  return model;
}

/** Load weights in Keras order: conv kernel; BN gamma, beta, moving mean, moving variance; dense kernel, bias. */
export function loadWeights(tf: TF, model: TF, m: Manifest, buffer: ArrayBuffer): void {
  const tensors = m.weights.map((w) => {
    const n = w.shape.reduce((a, b) => a * b, 1);
    return tf.tensor(new Float32Array(buffer, w.offset, n), w.shape);
  });
  let i = 0;
  for (const layer of model.layers) {
    const n = layer.getWeights().length;
    if (!n) continue;
    layer.setWeights(tensors.slice(i, i + n));
    i += n;
  }
  if (i !== tensors.length) throw new Error("photo model weights do not match its architecture");
}

/** Raw 0-255 pixels, channels-last (SIZE*SIZE*2), normalized exactly as in training. */
export function normalize(pixels: ArrayLike<number>): Float32Array {
  const out = new Float32Array(pixels.length);
  for (let i = 0; i < pixels.length; i++) out[i] = pixels[i] * (4 / 255) - 2;
  return out;
}

export function logits(tf: TF, model: TF, pixels: ArrayLike<number>): number[] {
  return tf.tidy(() => Array.from(model.predict(tf.tensor(normalize(pixels), [1, SIZE, SIZE, 2])).dataSync() as Float32Array));
}
