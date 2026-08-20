import { useEffect, useRef } from 'react';

// Complements useTabSwitchGuard - once the exam is in full-screen, exiting it (Esc, F11, or the
// browser's own chrome) is reported the same way as switching tabs. Browsers give a page no way
// to keep itself "the only thing visible" other than full-screen mode, so this is the realistic
// stand-in for "block everything except the exam window."
//
// Note this fires on a plain tab switch too: Chrome drops full-screen when its tab stops being
// the active one, so a tab switch usually raises fullscreen_exit alongside tab_switch. That's why
// fullscreen_exit is in the server's warnable set - see exam_session.WARNABLE_REASONS.
// `rearmKey` clears the once-only latch after a warning is acknowledged.
export default function useFullscreenGuard(active, onViolation, rearmKey = 0) {
  const firedRef = useRef(false);

  useEffect(() => {
    if (!active) return undefined;
    firedRef.current = false;

    function handleChange() {
      if (!document.fullscreenElement && !firedRef.current) {
        firedRef.current = true;
        onViolation('fullscreen_exit');
      }
    }

    document.addEventListener('fullscreenchange', handleChange);
    return () => document.removeEventListener('fullscreenchange', handleChange);
  }, [active, onViolation, rearmKey]);
}
