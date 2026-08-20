import { useEffect, useRef } from 'react';

// Reports a tab switch, window minimize, or window-blur while the exam screen is active.
// Matches the wireframe's own cepwfWatchTabSwitch script (visibilitychange + blur).
// onViolation receives the specific reason code ('tab_switch' vs 'window_blur') so the candidate
// sees exactly what triggered it, not one generic message for both.
//
// This hook does NOT decide the consequence. Leaving the exam window earns one warning before
// the attempt ends, and that count is held by the server (see exam_session.record_violation) -
// a browser-side counter would reset on reload. `rearmKey` is bumped by the caller after a
// warning is acknowledged, which re-runs this effect and clears the once-only latch so the next
// occurrence is reported too.
export default function useTabSwitchGuard(active, onViolation, rearmKey = 0) {
  const firedRef = useRef(false);

  useEffect(() => {
    if (!active) return undefined;
    firedRef.current = false;

    function trigger(reason) {
      if (firedRef.current) return;
      firedRef.current = true;
      onViolation(reason);
    }
    function handleVisibility() {
      if (document.hidden) trigger('tab_switch');
    }
    function handleBlur() {
      trigger('window_blur');
    }

    document.addEventListener('visibilitychange', handleVisibility);
    window.addEventListener('blur', handleBlur);
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      window.removeEventListener('blur', handleBlur);
    };
    // rearmKey is intentionally a dependency - changing it is how the caller re-arms the latch.
  }, [active, onViolation, rearmKey]);
}
