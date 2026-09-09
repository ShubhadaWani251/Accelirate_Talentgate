import { useEffect, useRef, useState } from 'react';

// Detects sustained talking on the shared mic stream via Silero VAD (through @ricky0123/vad-web),
// distinct from the tolerated brief/ambient noise the requirement explicitly allows. Silero VAD
// already discriminates voice from non-voice at the frame level; MIN_VOICE_DURATION_MS is a
// second, independent layer on top of that specifically to filter a single word, cough, or
// throat-clear - all genuine "speech" by the model's own definition, all well under a second.
const MIN_VOICE_DURATION_MS = 3000;

// Every asset self-hosted under Frontend/public/models/vad/, same reasoning as visionModels.js -
// Safe Exam Browser's URL filter only reliably allows the exam's own origin.
const BASE_ASSET_PATH = '/models/vad/';
const ONNX_WASM_BASE_PATH = '/models/vad/ort/';

/**
 * @param {React.MutableRefObject<MediaStream|null>} streamRef the exam's camera/mic stream
 * @param {boolean} active only guard while the exam is actually running
 * @param {(reason: string) => void} onViolation shared violation reporter
 * @returns {{voiceDetected: boolean}}
 */
export default function useVoiceActivityGuard(streamRef, active, onViolation) {
  const [voiceDetected, setVoiceDetected] = useState(false);
  const firedRef = useRef(false);

  useEffect(() => {
    if (!active) return undefined;
    const stream = streamRef.current;
    if (!stream || stream.getAudioTracks().length === 0) return undefined;

    let cancelled = false;
    let vad = null;
    let durationTimer = null;

    function clearPending() {
      if (durationTimer) {
        clearTimeout(durationTimer);
        durationTimer = null;
      }
    }

    import('@ricky0123/vad-web').then(({ MicVAD }) => MicVAD.new({
      // Reuses the exam's already-granted mic stream instead of requesting getUserMedia again;
      // pause/resume are no-ops because this stream is shared with the session recorder and the
      // VAD must never touch its track state.
      getStream: async () => streamRef.current,
      pauseStream: async () => {},
      resumeStream: async (s) => s,
      baseAssetPath: BASE_ASSET_PATH,
      onnxWASMBasePath: ONNX_WASM_BASE_PATH,
      model: 'v5',
      startOnLoad: false,
      // Avoids SharedArrayBuffer/cross-origin-isolation entirely - this app sets no COOP/COEP
      // headers, and single-threaded inference is plenty fast for a model this small run once
      // per audio frame.
      ortConfig: (ort) => { ort.env.wasm.numThreads = 1; },
      onSpeechStart: () => {
        durationTimer = setTimeout(() => {
          durationTimer = null;
          setVoiceDetected(true);
          if (!firedRef.current) {
            firedRef.current = true;
            onViolation('voice_detected');
          }
        }, MIN_VOICE_DURATION_MS);
      },
      onSpeechEnd: () => {
        clearPending();
        setVoiceDetected(false);
        firedRef.current = false;
      },
      // The library's own false-alarm retraction - a genuine trigger that turned out too short
      // to count as real speech. Must be treated the same as onSpeechEnd, or a retracted noise
      // could still count toward the sustained-duration timer.
      onVADMisfire: () => {
        clearPending();
        setVoiceDetected(false);
        firedRef.current = false;
      },
    })).then((instance) => {
      if (cancelled) {
        instance.destroy();
        return;
      }
      vad = instance;
      vad.start();
    }).catch(() => {
      // Model/asset load failure degrades to "no voice signal" rather than breaking the exam -
      // matches how a failed vision-model load leaves useVisionProctoringGuard simply inert.
    });

    return () => {
      cancelled = true;
      clearPending();
      vad?.destroy();
    };
  }, [active, streamRef, onViolation]);

  return { voiceDetected };
}
