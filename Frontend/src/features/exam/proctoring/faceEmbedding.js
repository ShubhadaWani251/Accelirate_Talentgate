import * as ort from 'onnxruntime-web';
import { getVisionModels } from './visionModels';
import { getFaceIdModel } from './faceIdModel';

// MediaPipe FaceLandmarker point indices for the 5 landmarks SFace's alignment needs (both eye
// centers, nose tip, both mouth corners) - visually verified against a real photo (each dot
// overlaid on the actual detected mesh landed on the intended eye/nose/mouth-corner) before
// trusting these numbers; not guessed from the 478-point topology alone.
const LANDMARK_INDICES = { leftEye: 468, rightEye: 473, nose: 1, mouthLeft: 61, mouthRight: 291 };

// The standard 112x112 ArcFace/SFace reference template these 5 points get warped onto - the same
// coordinates used across the whole ArcFace/InsightFace ecosystem, not specific to this codebase.
// Order must match LANDMARK_INDICES' insertion order above (left eye, right eye, nose, mouth
// left, mouth right).
const TEMPLATE = [
  [38.2946, 51.6963],
  [73.5318, 51.5014],
  [56.0252, 71.7366],
  [41.5493, 92.3655],
  [70.7299, 92.2041],
];

const ALIGNED_SIZE = 112;

/**
 * Least-squares similarity transform (rotation + uniform scale + translation, no reflection)
 * mapping `src` points onto `dst` points, via complex-number arithmetic - verified equivalent
 * (matches to floating-point precision) to the SVD-based "Umeyama" method the wider ArcFace/
 * InsightFace ecosystem uses for this exact 5-point alignment problem, without needing a general
 * linear-algebra/SVD implementation for what is always exactly this one fixed-size case.
 * @returns {[number, number, number, number, number, number]} [a, b, tx, ty] as used below,
 *   representing x' = a*x - b*y + tx, y' = b*x + a*y + ty
 */
function similarityTransform(src, dst) {
  const n = src.length;
  let zx = 0, zy = 0, Zx = 0, Zy = 0;
  for (let i = 0; i < n; i++) {
    zx += src[i][0] / n; zy += src[i][1] / n;
    Zx += dst[i][0] / n; Zy += dst[i][1] / n;
  }
  // c = sum(conj(u_i) * v_i) / sum(conj(u_i) * u_i), where u_i = z_i - mean(z), v_i = Z_i - mean(Z)
  // - the complex-number form of least-squares similarity-transform fitting.
  let num_re = 0, num_im = 0, den = 0;
  for (let i = 0; i < n; i++) {
    const ux = src[i][0] - zx, uy = src[i][1] - zy;
    const vx = dst[i][0] - Zx, vy = dst[i][1] - Zy;
    // conj(u) * v = (ux - i*uy) * (vx + i*vy) = (ux*vx + uy*vy) + i*(ux*vy - uy*vx)
    num_re += ux * vx + uy * vy;
    num_im += ux * vy - uy * vx;
    den += ux * ux + uy * uy;
  }
  const a = num_re / den;
  const b = num_im / den;
  const tx = Zx - (a * zx - b * zy);
  const ty = Zy - (b * zx + a * zy);
  return [a, b, tx, ty];
}

/**
 * @param {import('@mediapipe/tasks-vision').NormalizedLandmark[]} landmarks
 * @param {number} width source frame width in pixels
 * @param {number} height source frame height in pixels
 */
function landmarkPixelPoints(landmarks, width, height) {
  return Object.values(LANDMARK_INDICES).map((idx) => [
    landmarks[idx].x * width,
    landmarks[idx].y * height,
  ]);
}

/**
 * One face, aligned and embedded, from a single video/canvas frame - or null if the frame didn't
 * contain exactly one confidently-localized face (0 or 2+ faces are useVisionProctoringGuard's
 * job to flag, not this function's to guess about).
 *
 * @param {HTMLVideoElement|HTMLCanvasElement} source
 * @returns {Promise<Float32Array|null>} a 128-d embedding (not pre-normalized - use
 *   cosineSimilarity below, which handles that itself), or null
 */
export async function computeFaceEmbedding(source) {
  const { faceLandmarker } = await getVisionModels();
  const width = source.videoWidth ?? source.width;
  const height = source.videoHeight ?? source.height;
  const result = faceLandmarker.detectForVideo(source, performance.now());
  if (result.faceLandmarks.length !== 1) return null;

  const points = landmarkPixelPoints(result.faceLandmarks[0], width, height);
  const [a, b, tx, ty] = similarityTransform(points, TEMPLATE);

  const canvas = document.createElement('canvas');
  canvas.width = ALIGNED_SIZE;
  canvas.height = ALIGNED_SIZE;
  const ctx = canvas.getContext('2d');
  // Canvas transform convention: x' = a*x + c*y + e, y' = b*x + d*y + f - matches
  // similarityTransform's [a, b, tx, ty] as setTransform(a, b, -b, a, tx, ty).
  ctx.setTransform(a, b, -b, a, tx, ty);
  ctx.drawImage(source, 0, 0);

  const { data } = ctx.getImageData(0, 0, ALIGNED_SIZE, ALIGNED_SIZE);
  // RGBA HWC uint8 -> RGB CHW float32, raw 0-255 range, no mean/scale normalization - empirically
  // verified against OpenCV's own reference FaceRecognizerSF implementation of this exact model
  // (matched to ~0.99 cosine similarity on the correct combination; every other combination of
  // channel order / normalization scored far off), not assumed from convention alone.
  const chw = new Float32Array(3 * ALIGNED_SIZE * ALIGNED_SIZE);
  const plane = ALIGNED_SIZE * ALIGNED_SIZE;
  for (let p = 0; p < plane; p++) {
    chw[p] = data[p * 4];
    chw[plane + p] = data[p * 4 + 1];
    chw[2 * plane + p] = data[p * 4 + 2];
  }

  const session = await getFaceIdModel();
  const tensor = new ort.Tensor('float32', chw, [1, 3, ALIGNED_SIZE, ALIGNED_SIZE]);
  const outputs = await session.run({ [session.inputNames[0]]: tensor });
  return outputs[session.outputNames[0]].data;
}

export function cosineSimilarity(a, b) {
  let dot = 0, normA = 0, normB = 0;
  for (let i = 0; i < a.length; i++) {
    dot += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  return dot / (Math.sqrt(normA) * Math.sqrt(normB));
}
