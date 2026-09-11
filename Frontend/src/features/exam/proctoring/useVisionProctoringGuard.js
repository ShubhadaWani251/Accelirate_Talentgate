import { useEffect, useRef, useState } from 'react';
import { getVisionModels } from './visionModels';

// Watches the shared camera feed for two independent signals: is exactly one face visible, and
// is a forbidden object (phone/laptop/book/remote/tv) in frame. Structured after useCameraGuard -
// one offscreen <video> and one setInterval poll for the life of the exam, self-clearing latches
// rather than a parent-driven rearm.
//
// Self-clearing (not a `rearmKey`, unlike the discrete-event guards such as useTabSwitchGuard)
// is deliberate: face absence and object presence are CONTINUOUSLY OBSERVABLE states, not
// one-off events. A rearmKey bumped right after a "warned" response would reset the latch while
// the same phone is still visibly in frame, and the very next sample would re-fire immediately -
// burning through the whole 3-warning pool in seconds for what is really one continuous
// occurrence. Clearing only when the condition itself resolves (mirroring cameraOff exactly) is
// what makes "one warning, then a real second chance" actually hold.

// Sampling both models every second, not every frame: detectForVideo is synchronous and running
// two models back-to-back is meaningfully heavier than useCameraGuard's single pixel-stddev
// check, so a faster cadence would compete with the session recorder's own encoding for the same
// main thread.
const SAMPLE_MS = 1000;

// Longest of the three, and deliberately a full minute (at the 1s cadence above): looking down
// at the keyboard or notes, leaning back to think, or a moment of tracking loss while turning the
// head are all common and entirely benign, and candidates were being warned over ordinary
// looking-down well before a minute had passed at the previous, much shorter tolerance.
const CONSECUTIVE_FACE_ABSENT = 60;
// A positively-identified second face is more specific evidence than "no face", but a passerby
// crossing the background for a couple of seconds still deserves the same patience.
const CONSECUTIVE_FACE_EXTRA = 4;
// Matches useCameraGuard's own CONSECUTIVE_BLOCKED_CHECKS - an allow-listed, confidence-gated
// object detection is about as specific a signal as that pixel check.
const CONSECUTIVE_OBJECT_PRESENT = 3;

/**
 * @param {React.MutableRefObject<MediaStream|null>} streamRef the exam's camera/mic stream
 * @param {boolean} active only guard while the exam is actually running
 * @param {(reason: string, extra?: object) => void} onViolation shared violation reporter
 * @returns {{faceNotVisible: boolean, extraPersonDetected: boolean, forbiddenObjectDetected: boolean, forbiddenObjectType: string|null}}
 */
export default function useVisionProctoringGuard(streamRef, active, onViolation) {
  const [state, setState] = useState({
    faceNotVisible: false,
    extraPersonDetected: false,
    forbiddenObjectDetected: false,
    forbiddenObjectType: null,
  });

  const faceAbsentFiredRef = useRef(false);
  const faceExtraFiredRef = useRef(false);
  const objectFiredRef = useRef(false);

  useEffect(() => {
    if (!active) return undefined;
    const stream = streamRef.current;
    if (!stream || stream.getVideoTracks().length === 0) return undefined;

    let cancelled = false;
    let faceAbsentStreak = 0;
    let faceExtraStreak = 0;
    let objectStreak = 0;
    let lastObjectSeen = null;

    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;
    video.play().catch(() => {
      // Same reasoning as useCameraGuard: a slow/blocked autoplay just means detectForVideo sees
      // a 0-dimension frame for a tick or two, which the streak requirement already absorbs.
    });

    let faceLandmarker;
    let objectDetector;
    getVisionModels().then((models) => {
      if (cancelled) return;
      faceLandmarker = models.faceLandmarker;
      objectDetector = models.objectDetector;
    });

    function check() {
      if (cancelled || !faceLandmarker || !objectDetector) return;
      if (video.readyState < 2) return; // no frame decoded yet

      const now = performance.now();

      const faceResult = faceLandmarker.detectForVideo(video, now);
      const faceCount = faceResult.faceLandmarks ? faceResult.faceLandmarks.length : 0;

      if (faceCount === 0) {
        faceAbsentStreak += 1;
        faceExtraStreak = 0;
      } else if (faceCount > 1) {
        faceExtraStreak += 1;
        faceAbsentStreak = 0;
      } else {
        faceAbsentStreak = 0;
        faceExtraStreak = 0;
      }

      const faceNotVisible = faceAbsentStreak >= CONSECUTIVE_FACE_ABSENT;
      const extraPersonDetected = faceExtraStreak >= CONSECUTIVE_FACE_EXTRA;

      if (faceNotVisible && !faceAbsentFiredRef.current) {
        faceAbsentFiredRef.current = true;
        onViolation('face_not_visible');
      } else if (!faceNotVisible) {
        faceAbsentFiredRef.current = false;
      }

      if (extraPersonDetected && !faceExtraFiredRef.current) {
        faceExtraFiredRef.current = true;
        onViolation('extra_person_detected');
      } else if (!extraPersonDetected) {
        faceExtraFiredRef.current = false;
      }

      const objectResult = objectDetector.detectForVideo(video, now);
      const detection = (objectResult.detections || [])[0];

      if (detection) {
        objectStreak += 1;
        lastObjectSeen = {
          type: detection.categories[0].categoryName,
          confidence: detection.categories[0].score,
        };
      } else {
        objectStreak = 0;
        lastObjectSeen = null;
      }

      const forbiddenObjectDetected = objectStreak >= CONSECUTIVE_OBJECT_PRESENT;

      if (forbiddenObjectDetected && !objectFiredRef.current) {
        objectFiredRef.current = true;
        onViolation('forbidden_object_detected', {
          detected_object: lastObjectSeen.type,
          confidence: lastObjectSeen.confidence,
        });
      } else if (!forbiddenObjectDetected) {
        objectFiredRef.current = false;
      }

      setState({
        faceNotVisible,
        extraPersonDetected,
        forbiddenObjectDetected,
        forbiddenObjectType: forbiddenObjectDetected ? lastObjectSeen.type : null,
      });
    }

    const interval = setInterval(check, SAMPLE_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
      video.srcObject = null;
      // Deliberately does NOT close faceLandmarker/objectDetector - they are a page-lifetime
      // singleton owned by visionModels.js, not this hook.
    };
  }, [active, streamRef, onViolation]);

  return state;
}
