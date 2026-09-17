// Distinguishing "turned away from the screen" from "not detected at all".
//
// useVisionProctoringGuard used to treat every frame without a face identically, which meant a
// candidate looking down at paper to work through a question was indistinguishable from one who
// had walked off - and got warned for it, repeatedly, in a real sitting. Splitting the two needs
// a signal for WHERE a detected face is pointing, which is what this file provides.
//
// Deliberately 2D and deliberately simple. MediaPipe also exposes facialTransformationMatrixes,
// from which full Euler angles can be derived, but that needs the matrix's row/column-major
// convention to be exactly right and there is no way to confirm that without a camera in front
// of a running build - a silently transposed matrix would read pitch as yaw and fire warnings at
// candidates for facing forwards. The horizontal ratio below is checkable by hand, degrades
// predictably, and is the axis we can actually measure reliably.

// Nose tip. The single most stable, most universally-cited index in MediaPipe's 468/478-point
// face mesh; everything else here is derived from the landmark set as a whole rather than from
// named indices, so nothing depends on contour numbering being remembered correctly.
const NOSE_TIP = 1;

// How far the nose may sit from the horizontal centre of the face before we call it "turned
// away". 0 = hard left edge, 0.5 = centred, 1 = hard right edge, so 0.22 means the nose has to
// cross roughly 72% (or 28%) of the way across the face - a deliberate head turn of around
// 35-45 degrees, not a glance or a slight lean.
//
// Set conservatively on purpose. The cost of it being too tight is a candidate warned for
// nothing, which is the exact failure this whole change exists to stop; the cost of it being
// too loose is a head turn taking a second longer to notice, on a signal the session recording
// captures anyway.
const MAX_NOSE_OFFSET_FROM_CENTRE = 0.22;

/**
 * Where the nose sits horizontally across the face, 0 (one edge) to 1 (the other).
 * ~0.5 when facing the camera; approaches 0 or 1 as the head turns.
 * @param {Array<{x: number, y: number}>} landmarks one face's landmark list
 * @returns {number}
 */
export function noseOffsetRatio(landmarks) {
  if (!landmarks || landmarks.length <= NOSE_TIP) return 0.5;

  let minX = Infinity;
  let maxX = -Infinity;
  for (const point of landmarks) {
    if (point.x < minX) minX = point.x;
    if (point.x > maxX) maxX = point.x;
  }

  const width = maxX - minX;
  // A zero-width face cannot be reasoned about; report "centred" so a degenerate frame can
  // never be the thing that ends someone's assessment.
  if (!(width > 0)) return 0.5;

  return (landmarks[NOSE_TIP].x - minX) / width;
}

/**
 * True when a DETECTED face is turned away from the screen.
 * Says nothing about a face that wasn't detected - that case is handled separately, and
 * deliberately more leniently, by the guard itself.
 * @param {Array<{x: number, y: number}>} landmarks
 * @returns {boolean}
 */
export function isLookingAway(landmarks) {
  return Math.abs(noseOffsetRatio(landmarks) - 0.5) > MAX_NOSE_OFFSET_FROM_CENTRE;
}
