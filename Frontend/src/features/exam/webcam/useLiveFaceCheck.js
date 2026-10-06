import { useEffect, useRef, useState } from 'react';
import { createFrameClock, MAX_CREDIT_FACTOR } from '../proctoring/frameClock';
import { getVisionModels } from '../proctoring/visionModels';

const SAMPLE_MS = 500;

/**
 * Live "how many faces are visible right now" signal for the face-photo capture card.
 *
 * This GATES CAPTURE - ExamIdVerify passes it straight to PhotoCapture's `captureBlocked`, which
 * disables the button. It was documented as "purely advisory (never blocks capture)" long after
 * that stopped being true, which matters: an advisory hint may flicker freely, a gate may not.
 *
 * It still carries no sustained-detection latch, deliberately. The cost of a momentary bad
 * reading here is a button disabled for half a second, not a warning or a terminated exam, and
 * reacting instantly is what makes the hint track what the candidate is doing.
 *
 * A side effect of calling getVisionModels() this early is that it pre-warms the shared singleton
 * the in-exam proctoring guard needs moments later.
 *
 * @param {React.MutableRefObject<MediaStream|null>} streamRef
 * @param {boolean} active - only run while this card is actually showing its live preview
 * @returns {{faceCount: number|null, sawExtraFace: boolean}} faceCount is null until the first
 *   sample has run. sawExtraFace latches true if more than one face was seen at any point while
 *   active, so the capture request can report it even though capture itself is blocked while it
 *   is happening - otherwise a second person at identity verification leaves no trace at all.
 */
export default function useLiveFaceCheck(streamRef, active) {
  const [faceCount, setFaceCount] = useState(null);
  // Latched for the whole identity step rather than reset per sample, and deliberately NOT
  // cleared when `active` goes false: it is the record that a second person was present, and
  // the point is that it survives long enough to be sent with the capture.
  const sawExtraFaceRef = useRef(false);

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
    // Same staleness gate as the in-exam guards (see frameClock.js). A stalled element here
    // would report a frozen count of 1 and let a capture through with someone else in the room,
    // which is the one thing this check exists to prevent.
    const frameClock = createFrameClock(video);

    getVisionModels()
      .then(({ faceLandmarker }) => {
        if (cancelled) return;
        intervalId = setInterval(() => {
          if (video.readyState < 2) return;
          if (frameClock.observedMs(SAMPLE_MS * MAX_CREDIT_FACTOR) <= 0) return;

          const result = faceLandmarker.detectForVideo(video, performance.now());
          const count = result.faceLandmarks?.length ?? 0;
          if (count > 1) sawExtraFaceRef.current = true;
          setFaceCount(count);
        }, SAMPLE_MS);
      })
      .catch(() => {}); // a model-load failure leaves faceCount null, which keeps capture blocked

    return () => {
      cancelled = true;
      if (intervalId) clearInterval(intervalId);
      frameClock.stop();
      video.srcObject = null;
    };
  }, [active, streamRef]);

  return { faceCount, sawExtraFace: sawExtraFaceRef.current };
}
