// Loads the two MediaPipe vision models exactly once for the whole exam session, shared between
// useVisionProctoringGuard's face-count and object-detection checks. Both need the same WASM
// runtime, so loading them together avoids fetching it twice.
//
// Every asset path below is self-hosted under Frontend/public/models/ rather than pulled from
// MediaPipe's own CDN default - Safe Exam Browser's configurable URL filter can silently block a
// third-party fetch, and the exam's own origin is the one address SEB is guaranteed to already
// allow (the exam itself couldn't load otherwise).
import { FilesetResolver, FaceLandmarker, ObjectDetector } from '@mediapipe/tasks-vision';

const WASM_BASE_PATH = '/models/vision/wasm';
const FACE_MODEL_PATH = '/models/vision/face_landmarker.task';
const OBJECT_MODEL_PATH = '/models/vision/efficientdet_lite0.tflite';

// MediaPipe's own default is 1, which would make a second face structurally undetectable no
// matter how many people are actually in frame - this has to be raised explicitly.
const MAX_FACES = 3;

export const FORBIDDEN_OBJECT_CATEGORIES = ['cell phone', 'laptop', 'book', 'remote', 'tv'];
const OBJECT_SCORE_THRESHOLD = 0.6;

let modelsPromise = null;

/** @returns {Promise<{faceLandmarker: FaceLandmarker, objectDetector: ObjectDetector}>} */
export function getVisionModels() {
  if (!modelsPromise) {
    modelsPromise = FilesetResolver.forVisionTasks(WASM_BASE_PATH)
      .then((fileset) => Promise.all([
        FaceLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: FACE_MODEL_PATH },
          runningMode: 'VIDEO',
          numFaces: MAX_FACES,
        }),
        ObjectDetector.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: OBJECT_MODEL_PATH },
          runningMode: 'VIDEO',
          // Filters at the model level, so a detected person never comes back here at all - face
          // count from FaceLandmarker is the more reliable signal for "how many people", this
          // stays scoped to genuinely inanimate objects.
          categoryAllowlist: FORBIDDEN_OBJECT_CATEGORIES,
          scoreThreshold: OBJECT_SCORE_THRESHOLD,
          maxResults: 5,
        }),
      ]))
      .then(([faceLandmarker, objectDetector]) => ({ faceLandmarker, objectDetector }))
      .catch((err) => {
        // Reset so a later retry (e.g. the guard hook itself mounting) gets a fresh attempt
        // instead of permanently replaying the same rejected promise.
        modelsPromise = null;
        throw err;
      });
  }
  return modelsPromise;
}
