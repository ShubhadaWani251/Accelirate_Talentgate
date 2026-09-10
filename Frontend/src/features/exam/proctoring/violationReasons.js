// One real action often trips several guards at once: pressing F12 fires the key handler AND
// blurs the window as devtools takes focus; exiting full-screen can fire fullscreenchange AND a
// blur. `window_blur` is the catch-all that fires most readily, so without an explicit ranking
// the vaguest cause frequently wins the race and the candidate is told they "left the exam
// window" when they actually pressed a specific key.
//
// Higher number = more specific = preferred when several arrive together.
const PRIORITY = {
  window_blur: 1,       // catch-all: any focus loss
  tab_switch: 2,        // more specific than blur: the tab itself became hidden
  fullscreen_exit: 3,
  // Above the window reasons on purpose: switching the camera off often means opening OS camera
  // settings or another app, which blurs the window too. Without this, the vaguer window_blur
  // would win and the candidate would be told they left the window when the real, more specific
  // cause was the camera.
  camera_off: 4,
  system_issue: 4,      // device-level, not a candidate choice
  // Same tier as camera_off: by the time any of these four fires, the owning hook has already
  // spent several seconds confirming a sustained condition (see useVisionProctoringGuard /
  // useVoiceActivityGuard), unlike window_blur/tab_switch which fire instantly on the first raw
  // browser event - so they deserve at least that same precedence, not the default of 0 that
  // would let an unrelated window_blur silently win the race and hide the AI-specific message.
  face_not_visible: 4,
  extra_person_detected: 4,
  forbidden_object_detected: 4,
  voice_detected: 4,
  view_source_attempt: 5,
  devtools_attempt: 5,
  screenshot_attempt: 5, // deliberate keypresses - the most precise signal available
};

// How long to keep collecting after the first trigger before committing to a reason. Sized for
// the worst realistic ordering: Print Screen can fire its focus-loss event first and deliver the
// key event only on RELEASE, so this has to outlast a slow press-and-release. Imperceptible to
// the candidate, since the attempt is already over by the time this elapses.
export const REASON_SETTLE_MS = 500;

export function moreSpecificReason(a, b) {
  if (!a) return b;
  if (!b) return a;
  return (PRIORITY[b] ?? 0) > (PRIORITY[a] ?? 0) ? b : a;
}
