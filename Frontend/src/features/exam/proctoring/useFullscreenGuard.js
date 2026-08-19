import { useEffect, useRef } from 'react';

// Complements useTabSwitchGuard - once the exam is in full-screen, exiting it (Esc, F11, or the
// browser's own chrome) is the same zero-tolerance violation as switching tabs. Browsers give a
// page no way to keep itself "the only thing visible" other than full-screen mode, so this is
// the realistic stand-in for "block everything except the exam window."
export default function useFullscreenGuard(active, onViolation) {
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
  }, [active, onViolation]);
}
