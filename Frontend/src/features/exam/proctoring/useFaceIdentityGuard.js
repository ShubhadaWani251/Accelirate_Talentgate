import { useEffect, useState } from 'react';
import { computeFaceEmbedding, cosineSimilarity } from './faceEmbedding';

// Heavier per-sample cost than useVisionProctoringGuard's checks (a similarity-transform
// alignment warp plus a CNN forward pass, not one already-optimized MediaPipe call) - and unlike
// a face vanishing from frame for a second, a genuine person-swap is an inherently multi-second
// real-world event (someone has to get up, someone else has to sit down), so nothing is gained by
// sampling faster than this.
const SAMPLE_MS = 5000;

// OpenCV's own published operating point for this exact model: cosine similarity >= 0.363 is
// "same identity" at 99.60% pair accuracy on LFW. Set deliberately BELOW that calibrated boundary:
// LFW is curated, well-lit, front-facing photography - an easier condition than a compressed
// webcam feed at a candidate's own desk, so a genuine same-person score is expected to read lower
// here even with zero impersonation. An actual impostor's score does not merely dip under the
// textbook boundary, it falls far below it, so this costs little real detection power while
// absorbing exactly the webcam-condition gap this model has never been validated against here.
const SIMILARITY_THRESHOLD = 0.30;

// Four straight misses (>=20s of continuously low similarity, at the 5s cadence above) before
// this fires. Long enough that a single bad sample - a hard head turn losing alignment quality for
// one frame, a glare crossing the face for a moment - never counts alone, since those resolve
// within a sample or two once the candidate settles back. Short enough that a real handoff to a
// different person - which, unlike those causes, never self-corrects back to a high score - is
// still caught well inside one exam section, not discovered only at grading time.
const CONSECUTIVE_LOW_SIMILARITY = 4;

/**
 * @param {React.MutableRefObject<MediaStream|null>} streamRef the exam's camera/mic stream
 * @param {React.MutableRefObject<Float32Array|null>} baselineEmbeddingRef the ID-verify baseline
 *   embedding, threaded from ExamSessionProvider - populated here if it's still empty (e.g. a
 *   page reload wiped it, same as it wipes streamRef - see ExamIdVerify.jsx's own capture effect
 *   for the primary path)
 * @param {boolean} active only guard while the exam is actually running
 * @param {(reason: string, extra?: object) => void} onViolation shared violation reporter
 * @returns {{identityMismatch: boolean}}
 */
export default function useFaceIdentityGuard(streamRef, baselineEmbeddingRef, active, onViolation) {
  const [identityMismatch, setIdentityMismatch] = useState(false);

  useEffect(() => {
    if (!active) {
      setIdentityMismatch(false);
      return undefined;
    }
    const stream = streamRef.current;
    if (!stream) return undefined;

    let cancelled = false;
    let tickInFlight = false;
    let mismatchStreak = 0;
    // Self-clearing latch, not a rearmKey: face identity is a continuously-observable state, not
    // a one-off discrete event - re-arming on the server's "warned" response (rather than on the
    // condition actually resolving) would let the same ongoing mismatch immediately re-fire and
    // burn the shared warning pool in seconds. Mirrors useVisionProctoringGuard's own reasoning.
    let mismatchFired = false;

    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;
    video.play().catch(() => {});

    async function check() {
      // detectForVideo/onnxruntime's session.run are both Promise-based (unlike
      // useVisionProctoringGuard's synchronous MediaPipe calls) - this guard against a slow tick
      // overlapping the next setInterval firing before the previous one resolves.
      if (cancelled || tickInFlight || video.readyState < 2) return;
      tickInFlight = true;
      try {
        if (!baselineEmbeddingRef.current) {
          // Fallback path only - see this hook's own docstring. The primary baseline capture
          // happens once, at ID-verification time, in ExamIdVerify.jsx.
          const baseline = await computeFaceEmbedding(video);
          if (baseline) baselineEmbeddingRef.current = baseline;
          return;
        }

        const sample = await computeFaceEmbedding(video);
        if (cancelled) return;
        // 0 or 2+ faces - that's face_not_visible/extra_person_detected's job to flag, not this
        // hook's; skip the tick entirely rather than treating it as a mismatch signal.
        if (!sample) return;

        const similarity = cosineSimilarity(baselineEmbeddingRef.current, sample);
        mismatchStreak = similarity < SIMILARITY_THRESHOLD ? mismatchStreak + 1 : 0;
        const mismatch = mismatchStreak >= CONSECUTIVE_LOW_SIMILARITY;

        if (mismatch && !mismatchFired) {
          mismatchFired = true;
          // Never surfaced to the UI (see this hook's returned shape) - only sent as evidence on
          // an actual violation report, same as forbidden_object_detected's own {detected_object,
          // confidence} extra_details, so a bad-faith candidate can't watch their own score and
          // learn exactly where the line is.
          onViolation('face_mismatch', { similarity });
        } else if (!mismatch) {
          mismatchFired = false;
        }
        setIdentityMismatch(mismatch);
      } catch {
        // A model/inference failure degrades to "no signal this tick" - matches how a failed
        // vision-model load leaves useVisionProctoringGuard simply inert, never blocking the exam.
      } finally {
        tickInFlight = false;
      }
    }

    const intervalId = setInterval(check, SAMPLE_MS);

    return () => {
      cancelled = true;
      clearInterval(intervalId);
      video.srcObject = null;
    };
  }, [active, streamRef, baselineEmbeddingRef, onViolation]);

  return { identityMismatch };
}
