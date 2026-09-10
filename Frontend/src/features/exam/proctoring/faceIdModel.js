import * as ort from 'onnxruntime-web';

// SFace (OpenCV Zoo, Apache-2.0), INT8-quantized - a 1:1 "is this still the same person" face
// embedding model, not open-set recognition. Chosen over the more commonly-cited InsightFace/
// ArcFace model packages, which are explicitly non-commercial-only licensed - a hard blocker for
// a commercial product.
const MODEL_PATH = '/models/faceid/sface_2021dec_int8.onnx';

// Reuses the exact WASM binary already self-hosted for useVoiceActivityGuard's onnxruntime-web
// instance (same resolved package version, ^1.22.0 per package-lock.json) rather than vendoring a
// second ~11MB copy of the identical file under a new path. @ricky0123/vad-web owns its own
// onnxruntime-web module instance internally - this file's `import * as ort` is a separate module
// graph with its own independent `ort.env`, so pointing both at the same files on disk is safe,
// not a shared/coupled runtime.
const ONNX_WASM_BASE_PATH = '/models/vad/ort/';

let modelPromise = null;

/** @returns {Promise<import('onnxruntime-web').InferenceSession>} */
export function getFaceIdModel() {
  if (!modelPromise) {
    ort.env.wasm.wasmPaths = ONNX_WASM_BASE_PATH;
    // No COOP/COEP headers are set anywhere in this app, so the threaded/SharedArrayBuffer path
    // isn't available regardless - same reasoning and setting as useVoiceActivityGuard's.
    ort.env.wasm.numThreads = 1;
    modelPromise = ort.InferenceSession.create(MODEL_PATH, {
      // Explicit, not left to auto-detection: onnxruntime-web 1.22's default provider probing
      // (webgpu/webnn first) resolves to its JSEP-compiled WASM binary even to determine those
      // backends are unavailable, and only the plain (non-JSEP) binary is vendored here (matching
      // useVoiceActivityGuard's own vendored files) - forcing 'wasm' up front avoids that probe
      // entirely rather than vendoring a second ~11MB JSEP binary nothing else in this app needs.
      executionProviders: ['wasm'],
    })
      .catch((err) => {
        modelPromise = null;
        throw err;
      });
  }
  return modelPromise;
}
