import { useEffect, useRef, useState } from 'react';
import { createFrameClock, MAX_CREDIT_FACTOR } from './frameClock';
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

// Every threshold below is MILLISECONDS OF CAMERA FOOTAGE ACTUALLY OBSERVED, not a count of
// samples, and the difference is the whole reason this file was rewritten on 2026-10-06.
//
// These used to be sample counts reasoned about as seconds - "15 samples at 1s is 15 seconds".
// That holds only while frames keep arriving. The offscreen <video> below lives on the main
// thread, and when the main thread is starved (two models a second, plus the session recorder's
// encoder, plus whatever else the machine is doing) it STALLS: readyState stays >= 2, so the old
// guard happily re-analysed the SAME FRAME every tick and every streak completed on one frame.
// Head-turn needed two samples - its comment said that was "to discard a single bad frame", and
// a frozen frame is both of them. Three candidates were terminated this way during load testing
// on 2026-10-05, for an object, a head turn and a lost camera that the session recordings show
// never happened. The recording stayed truthful because MediaRecorder reads the MediaStream
// directly in the media pipeline, not through this element.
//
// Time is now measured from video.currentTime, the element's own media clock. It advances only
// when real frames are decoded, so a stalled element contributes nothing and a throttled timer
// cannot change what "15 seconds" means. See the staleness check in check().
const FACE_ABSENT_MS = 15000;
const LOOKING_AWAY_MS = 2000;
const FACE_EXTRA_MS = 4000;
const OBJECT_ABSENT_TO_REARM_MS = 5000;

const MAX_CREDIT_MS = SAMPLE_MS * MAX_CREDIT_FACTOR;

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
//
// FACE DETECTED BUT TURNED AWAY - 2 seconds.
//
// The unambiguous half of the split. Here the face IS tracked and is pointing away from the
// screen (see headPose.js), which nothing about answering a question requires - unlike looking
// down, which is why that case is handled by the longer tolerance above.
//
// 2 seconds rather than instant, to discard a bad frame: motion blur or a lighting flicker can
// momentarily skew the landmark positions, and one glitched frame should not cost a candidate a
// warning. That is only true of two seconds of GENUINELY DIFFERENT frames, which is what the
// staleness check now guarantees and what this tolerance always assumed.
//
// EXTRA FACE - 4 seconds. A positively-identified second face is more specific evidence than
// "no face", but a passerby crossing the background still deserves the same patience.
//
// FORBIDDEN OBJECT - no tolerance at all: it warns on the first fresh, confident detection.
// Already gated by visionModels.js's own scoreThreshold (0.6) and categoryAllowlist, so that is
// still a confidence-checked, allow-listed signal, not a raw one.
//
// ...but re-arming is a different question from firing, and needs OBJECT_ABSENT_TO_REARM_MS of
// clear view. A detection sitting near the confidence threshold does not hold steady, it
// oscillates; the latch used to clear on a single clear sample, so detected/gone/detected read
// as two occurrences a second apart, and four of those spent the whole warning pool in about six
// seconds. Testers hit exactly that on 2026-10-05. Five seconds of genuinely nothing in frame is
// what now counts as "put away": someone who pockets a phone waits that out once, a flickering
// score never does.

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
    // Milliseconds of observed footage each condition has held for, not sample counts - see the
    // thresholds at the top of this file.
    let faceAbsentMs = 0;
    let faceExtraMs = 0;
    let lookingAwayMs = 0;
    // Tracked separately from "object present" rather than inferred from it: presence resets to
    // 0 on the first clear sample, which cannot distinguish "clear for one frame" from "clear
    // for five seconds", and that distinction is the whole point of the re-arm delay.
    let objectAbsentMs = 0;
    let lastObjectSeen = null;

    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;
    video.play().catch(() => {
      // Same reasoning as useCameraGuard: a slow/blocked autoplay just means no frames arrive
      // yet, which the frame clock reports as "nothing observed" rather than as evidence.
    });
    const frameClock = createFrameClock(video);

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

      // THE STALENESS GATE - see frameClock.js. Returning early rather than treating a repeated
      // frame as evidence either way is the point: with no new observation, no condition may
      // advance AND none may be cleared, so a frozen frame costs exactly nothing in either
      // direction.
      const observedMs = frameClock.observedMs(MAX_CREDIT_MS);
      if (observedMs <= 0) return;

      const now = performance.now();

      const faceResult = faceLandmarker.detectForVideo(video, now);
      const faceCount = faceResult.faceLandmarks ? faceResult.faceLandmarks.length : 0;

      if (faceCount === 0) {
        faceAbsentMs += observedMs;
        faceExtraMs = 0;
        lookingAwayMs = 0;
      } else if (faceCount > 1) {
        faceExtraMs += observedMs;
        faceAbsentMs = 0;
        lookingAwayMs = 0;
      } else {
        faceAbsentMs = 0;
        faceExtraMs = 0;
        // Exactly one face, so its orientation is a meaningful question. Looking down keeps the
        // nose centred horizontally and so reads as facing forward here - correctly, since the
        // longer face-absent tolerance is what covers that case.
        lookingAwayMs = isLookingAway(faceResult.faceLandmarks[0])
          ? lookingAwayMs + observedMs
          : 0;
      }

      const faceNotVisible = faceAbsentMs >= FACE_ABSENT_MS;
      const extraPersonDetected = faceExtraMs >= FACE_EXTRA_MS;
      const lookingAway = lookingAwayMs >= LOOKING_AWAY_MS;

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
        objectAbsentMs = 0;
        lastObjectSeen = {
          type: detection.categories[0].categoryName,
          confidence: detection.categories[0].score,
        };
      } else {
        objectAbsentMs += observedMs;
        lastObjectSeen = null;
      }

      // No tolerance: a device warns on the first fresh, confident detection. "Fresh" is now
      // load-bearing - this is the check that used to fire on a repeat of a frozen frame.
      const forbiddenObjectDetected = Boolean(detection);

      if (forbiddenObjectDetected && !objectFiredRef.current) {
        objectFiredRef.current = true;
        onViolation('forbidden_object_detected', {
          detected_object: lastObjectSeen.type,
          confidence: lastObjectSeen.confidence,
        });
      } else if (objectAbsentMs >= OBJECT_ABSENT_TO_REARM_MS) {
        // Re-arms only after a sustained clear view, not on the first blank sample - which is
        // what stops one oscillating detection being charged as several occurrences.
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
      frameClock.stop();
      video.srcObject = null;
      // Deliberately does NOT close faceLandmarker/objectDetector - they are a page-lifetime
      // singleton owned by visionModels.js, not this hook.
    };
  }, [active, streamRef, onViolation]);

  return state;
}
