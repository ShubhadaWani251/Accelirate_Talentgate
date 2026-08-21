import { useCallback, useEffect, useState } from 'react';

// Refuses the exam while more than one display is attached.
//
// This is the closest thing to "detect screen sharing" that a web page can actually do, and it
// is worth being honest about the gap: a browser CANNOT tell that Teams, Zoom or OBS is sharing
// the screen. Screen capture happens at the OS level and no shipped web API reports it - the
// same reason Win+Shift+S and phone cameras are undetectable. Anything claiming otherwise in a
// web app is guessing.
//
// What IS detectable is the setup that makes sharing useful for cheating: a second display, so
// the candidate can put the exam on one screen and a helper (or the shared view) on the other.
// The Window Management API exposes exactly that, and it is checked continuously - plugging a
// monitor in mid-exam is caught, not just at the start.
//
// Two deliberate limitations:
//  - screen.isExtended is available on Chromium (Chrome/Edge 100+). On Firefox and Safari it is
//    undefined, and this hook then reports "supported: false" rather than pretending the machine
//    has one screen. The caller decides what to do with an unsupported browser; it must not
//    silently read as a pass.
//  - It counts displays, not what is on them. A candidate mirroring one display, or sharing
//    their single screen, is not caught. Session recording remains the backstop for that.

export const DISPLAY_DETECTION_SUPPORTED =
  typeof window !== 'undefined'
  && typeof window.screen !== 'undefined'
  && 'isExtended' in window.screen;

export function hasExtendedDisplay() {
  if (!DISPLAY_DETECTION_SUPPORTED) return false;
  return Boolean(window.screen.isExtended);
}

/**
 * Watches the display configuration for the whole time `active` is true.
 *
 * Returns { extended, supported }. `extended` true means more than one display is currently
 * attached. The caller gates the exam on it (see ExamIdVerify for the pre-start block and
 * ExamAttemptPage for the mid-exam one) rather than this hook terminating anything itself -
 * the same reason the other proctoring hooks only report: one place decides consequences.
 */
export default function useDisplayGuard(active = true) {
  const [extended, setExtended] = useState(() => hasExtendedDisplay());

  const refresh = useCallback(() => setExtended(hasExtendedDisplay()), []);

  useEffect(() => {
    if (!active || !DISPLAY_DETECTION_SUPPORTED) return undefined;
    refresh();

    // `change` on screen fires when displays are added/removed. Chrome only dispatches it once
    // the page holds window-management permission, which it may not - so it is paired with a
    // poll rather than relied on alone. 4s is frequent enough that a monitor plugged in
    // mid-exam is caught while the candidate is still on the same question, and cheap enough
    // (one property read) to be unnoticeable.
    const screenTarget = window.screen;
    screenTarget.addEventListener?.('change', refresh);
    const poll = window.setInterval(refresh, 4000);

    // A candidate returning to the tab is the most likely moment for the setup to have changed.
    document.addEventListener('visibilitychange', refresh);

    return () => {
      screenTarget.removeEventListener?.('change', refresh);
      window.clearInterval(poll);
      document.removeEventListener('visibilitychange', refresh);
    };
  }, [active, refresh]);

  return { extended, supported: DISPLAY_DETECTION_SUPPORTED, refresh };
}
