import { useEffect, useState } from 'react';
import { getVisionModels } from '../proctoring/visionModels';

const SAMPLE_MS = 500;

/**
 * Live, undebounced "is exactly one face visible right now" signal for the face-photo capture
 * card - purely advisory (never blocks capture), so unlike useVisionProctoringGuard this needs no
 * sustained-detection latch: nothing is at stake if a momentary bad reading flickers, so it can
 * react instantly either way. A side effect of calling getVisionModels() this early is that it
 * pre-warms the shared singleton the in-exam proctoring guard needs moments later.
 *
 * @param {React.MutableRefObject<MediaStream|null>} streamRef
 * @param {boolean} active - only run while this card is actually showing its live preview
 * @returns {{faceCount: number|null}} null until the first sample has run
 */
export default function useLiveFaceCheck(streamRef, active) {
  const [faceCount, setFaceCount] = useState(null);

  useEffect(() => {
    if (!active || !streamRef.current) {
      setFaceCount(null);
      return undefined;
    }

    let cancelled = false;
    let intervalId = null;
    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.srcObject = streamRef.current;
    video.play().catch(() => {});

    getVisionModels()
      .then(({ faceLandmarker }) => {
        if (cancelled) return;
        intervalId = setInterval(() => {
          if (video.readyState < 2) return;
          const result = faceLandmarker.detectForVideo(video, performance.now());
          setFaceCount(result.faceLandmarks?.length ?? 0);
        }, SAMPLE_MS);
      })
      .catch(() => {}); // advisory only - a model-load failure just means no live hint is shown

    return () => {
      cancelled = true;
      if (intervalId) clearInterval(intervalId);
      video.srcObject = null;
    };
  }, [active, streamRef]);

  return { faceCount };
}
