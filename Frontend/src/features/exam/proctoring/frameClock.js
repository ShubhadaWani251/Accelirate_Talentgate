/** "Has this <video> actually shown me a new frame since I last looked, and how much footage?"
 *
 * Every proctoring guard samples an offscreen <video> on a timer and judges what it sees. None of
 * them used to ask this question. `readyState >= 2` only says a frame EXISTS - it says nothing
 * about whether it is a new one. Those elements live on the main thread, and when that thread is
 * starved (two vision models a second, a video encoder, and whatever else the machine is doing)
 * they stall: the same frame is handed back tick after tick, every re-analysis reaches the same
 * verdict, and every "N consecutive samples" tolerance completes on a single frozen frame.
 *
 * Three candidates were terminated that way during load testing on 2026-10-05 - for an object, a
 * head turn and a lost camera that their session recordings show never happened. The recordings
 * stayed truthful because MediaRecorder reads the MediaStream directly in the browser's media
 * pipeline; only the guards were looking through a frozen window.
 *
 * Shared rather than written into each guard because the check is subtle in a way that would not
 * survive being copied four times - and because getting it wrong is silent in both directions:
 * too strict and proctoring quietly stops, too loose and it goes back to terminating people.
 *
 * TWO SOURCES, because neither is reliable alone:
 *
 *   requestVideoFrameCallback is the purpose-built answer - it fires once per PRESENTED frame
 *   and reports that frame's own mediaTime. If it has not fired, no frame was presented, which
 *   is exactly the question being asked. Preferred wherever it exists.
 *
 *   video.currentTime is the fallback. It is the right idea but not guaranteed to be frame-
 *   driven: for a MediaStream source a browser may advance it from a clock rather than from
 *   presentation, in which case it would keep ticking through a stall and defeat the whole check.
 *   Used only when rVFC is unavailable, where a weaker check still beats none.
 */

/** Milliseconds a single sample may ever be credited with, as a multiple of the sample interval.
 *
 * A stalled element that resumes can report a large jump at once. Crediting all of it would hand
 * a condition several seconds of "observation" from one frame - the same bug wearing a different
 * hat - so no tick is ever worth more than two normal samples. */
export const MAX_CREDIT_FACTOR = 2;

/**
 * @param {HTMLVideoElement} video an element with a MediaStream already attached
 * @returns {{observedMs: (maxCreditMs: number) => number, stop: () => void}}
 */
export function createFrameClock(video) {
  const hasRvfc = typeof video.requestVideoFrameCallback === 'function';

  // Updated only from inside the frame callback, so they move if and only if a frame was shown.
  let presentedFrames = 0;
  let presentedMediaTime = null;
  let rvfcHandle = null;
  let stopped = false;

  if (hasRvfc) {
    const onFrame = (_now, metadata) => {
      if (stopped) return;
      presentedFrames += 1;
      presentedMediaTime = metadata.mediaTime;
      rvfcHandle = video.requestVideoFrameCallback(onFrame);
    };
    rvfcHandle = video.requestVideoFrameCallback(onFrame);
  }

  let lastFrames = null;
  let lastTime = null;

  return {
    /** New footage since the previous call, in ms, or 0 if the element has not advanced.
     *
     * The FIRST call always returns 0: it establishes the baseline and credits nothing, so a
     * guard can never bank time it was not running for. */
    observedMs(maxCreditMs) {
      const useRvfc = hasRvfc && presentedMediaTime !== null;
      const time = useRvfc ? presentedMediaTime : video.currentTime;
      const frames = useRvfc ? presentedFrames : null;

      if (lastTime === null) {
        lastTime = time;
        lastFrames = frames;
        return 0;
      }
      // No frame presented since the last look - the decisive test where rVFC exists, and the
      // one currentTime alone cannot be trusted to answer.
      if (frames !== null && frames === lastFrames) return 0;
      if (!(time > lastTime)) return 0;

      const elapsedMs = (time - lastTime) * 1000;
      lastTime = time;
      lastFrames = frames;
      return Math.min(elapsedMs, maxCreditMs);
    },

    stop() {
      stopped = true;
      if (rvfcHandle !== null && typeof video.cancelVideoFrameCallback === 'function') {
        video.cancelVideoFrameCallback(rvfcHandle);
      }
    },
  };
}
