import { useEffect, useRef, useState } from 'react';
import { getVisionModels } from './visionModels';
import { isLookingAway } from './headPose';

// Watches the shared camera feed for two independent signals: is exactly one face visible, and
// is a forbidden electronic device (phone/laptop/remote/tv) in frame. Structured after useCameraGuard -
// one offscreen <video> and one setInterval poll for the life of the exam, self-clearing latches
// rather than a parent-driven rearm.
//
// Self-clearing (not a `rearmKey`, unlike the discrete-event guards such as useTabSwitchGuard)
// is deliberate: face absence and object presence are CONTINUOUSLY OBSERVABLE states, not
// one-off events. A rearmKey bumped right after a "warned" response would reset the latch while
// the same phone is still visibly in frame, and the very next sample would re-fire immediately -
// burning through the whole 3-warning pool in seconds for what is really one continuous
// occurrence. Clearing only when the condition itself resolves (mirroring cameraOff exactly) is
// what makes each genuine occurrence cost exactly one of the three shared warnings.

// Sampling both models every second, not every frame: detectForVideo is synchronous and running
// two models back-to-back is meaningfully heavier than useCameraGuard's single pixel-stddev
// check, so a faster cadence would compete with the session recorder's own encoding for the same
// main thread.
const SAMPLE_MS = 1000;

// NO FACE DETECTED AT ALL - 15 seconds.
//
// This case is genuinely ambiguous and has to be treated as such. MediaPipe loses the face
// entirely once the head pitches down far enough, so a candidate doing rough work on paper
// produces exactly the same signal as one who has walked off: zero faces. They cannot be told
// apart from this input, and warning immediately on it is what caused real candidates to be
// warned three times in a single sitting for reading their own desk.
//
// 15 seconds is long enough to cover working through a question on paper, and short enough that
// a genuine absence is still caught quickly. The residual cost - someone can be away for up to
// 15s unwarned - is covered by the session recording, and by useFaceIdentityGuard, which still
// catches a person SWAP within ~6s regardless of this number. That is the threat that actually
// matters; this check only ever meant "is the candidate visibly present".
const CONSECUTIVE_FACE_ABSENT = 15;

// FACE DETECTED BUT TURNED AWAY - effectively immediate.
//
// The unambiguous half of the split. Here the face IS tracked and is pointing away from the
// screen (see headPose.js), which nothing about answering a question requires - unlike looking
// down, which is why that case is handled by the streak above instead.
//
// 2 samples rather than 1 purely to discard a single bad frame: motion blur or a lighting
// flicker can momentarily skew the landmark positions, and one glitched frame should not cost a
// candidate a warning. At a 1s cadence this still reports within about two seconds.
const CONSECUTIVE_LOOKING_AWAY = 2;
// A positively-identified second face is more specific evidence than "no face", but a passerby
// crossing the background for a couple of seconds still deserves the same patience.
const CONSECUTIVE_FACE_EXTRA = 4;
// Deliberately 1, not a streak - a forbidden object must warn on the very first confident
// detection, no delay. Already gated by visionModels.js's own scoreThreshold (0.6) and
// categoryAllowlist, so "first detection" is still a confidence-checked, allow-listed signal,
// not a raw, unfiltered one.
const CONSECUTIVE_OBJECT_PRESENT = 1;

// getVisionModels() resets its own cached promise on failure specifically so a later call gets a
// fresh attempt rather than replaying the same rejection (see visionModels.js) - but neither of
// its two callers actually did that until now. Without a retry here, one transient failure
// loading the ~20MB of WASM/model assets (a slow connection, a momentary network blip) silently
// left faceLandmarker/objectDetector undefined for good: check() below no-ops whenever either is
// missing, so BOTH face-visibility and object detection would go dark for the rest of the exam
// with nothing in the UI to show it. 5 attempts, 3s apart, gives a real network hiccup room to
// clear without retrying forever into an exam that's already moved on.
const MODEL_LOAD_MAX_ATTEMPTS = 5;
const MODEL_LOAD_RETRY_MS = 3000;

/**
 * @param {React.MutableRefObject<MediaStream|null>} streamRef the exam's camera/mic stream
 * @param {boolean} active only guard while the exam is actually running
 * @param {(reason: string, extra?: object) => void} onViolation shared violation reporter
 * @returns {{faceNotVisible: boolean, extraPersonDetected: boolean, forbiddenObjectDetected: boolean, forbiddenObjectType: string|null}}
 */
export default function useVisionProctoringGuard(streamRef, active, onViolation) {
  const [state, setState] = useState({
    faceNotVisible: false,
    lookingAway: false,
    extraPersonDetected: false,
    forbiddenObjectDetected: false,
    forbiddenObjectType: null,
  });

  const faceAbsentFiredRef = useRef(false);
  const faceExtraFiredRef = useRef(false);
  const lookingAwayFiredRef = useRef(false);
  const objectFiredRef = useRef(false);

  useEffect(() => {
    if (!active) return undefined;
    const stream = streamRef.current;
    if (!stream || stream.getVideoTracks().length === 0) return undefined;

    let cancelled = false;
    let faceAbsentStreak = 0;
    let faceExtraStreak = 0;
    let lookingAwayStreak = 0;
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
    let retryTimer = null;

    function loadModels(attemptsSoFar) {
      getVisionModels()
        .then((models) => {
          if (cancelled) return;
          faceLandmarker = models.faceLandmarker;
          objectDetector = models.objectDetector;
        })
        .catch(() => {
          if (cancelled || attemptsSoFar >= MODEL_LOAD_MAX_ATTEMPTS) return;
          retryTimer = setTimeout(() => loadModels(attemptsSoFar + 1), MODEL_LOAD_RETRY_MS);
        });
    }
    loadModels(0);

    function check() {
      if (cancelled || !faceLandmarker || !objectDetector) return;
      if (video.readyState < 2) return; // no frame decoded yet

      const now = performance.now();

      const faceResult = faceLandmarker.detectForVideo(video, now);
      const faceCount = faceResult.faceLandmarks ? faceResult.faceLandmarks.length : 0;

      if (faceCount === 0) {
        faceAbsentStreak += 1;
        faceExtraStreak = 0;
        lookingAwayStreak = 0;
      } else if (faceCount > 1) {
        faceExtraStreak += 1;
        faceAbsentStreak = 0;
        lookingAwayStreak = 0;
      } else {
        faceAbsentStreak = 0;
        faceExtraStreak = 0;
        // Exactly one face, so its orientation is a meaningful question. Looking down keeps the
        // nose centred horizontally and so reads as facing forward here - correctly, since the
        // streak above is what covers that case.
        lookingAwayStreak = isLookingAway(faceResult.faceLandmarks[0]) ? lookingAwayStreak + 1 : 0;
      }

      const faceNotVisible = faceAbsentStreak >= CONSECUTIVE_FACE_ABSENT;
      const extraPersonDetected = faceExtraStreak >= CONSECUTIVE_FACE_EXTRA;
      const lookingAway = lookingAwayStreak >= CONSECUTIVE_LOOKING_AWAY;

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

      if (lookingAway && !lookingAwayFiredRef.current) {
        lookingAwayFiredRef.current = true;
        onViolation('looking_away');
      } else if (!lookingAway) {
        lookingAwayFiredRef.current = false;
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
        lookingAway,
        extraPersonDetected,
        forbiddenObjectDetected,
        forbiddenObjectType: forbiddenObjectDetected ? lastObjectSeen.type : null,
      });
    }

    const interval = setInterval(check, SAMPLE_MS);

    return () => {
      cancelled = true;
      clearInterval(interval);
      clearTimeout(retryTimer);
      video.srcObject = null;
      // Deliberately does NOT close faceLandmarker/objectDetector - they are a page-lifetime
      // singleton owned by visionModels.js, not this hook.
    };
  }, [active, streamRef, onViolation]);

  return state;
}
