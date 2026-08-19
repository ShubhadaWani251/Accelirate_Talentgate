import { useEffect, useRef } from 'react';

// Zero-tolerance: the FIRST tab switch, window minimize, or window-blur while the exam screen
// is active ends the attempt immediately - no warning tier, no violation count. Matches the
// wireframe's own cepwfWatchTabSwitch script (visibilitychange + blur). onViolation receives the
// specific reason code ('tab_switch' vs 'window_blur') so the candidate sees exactly what
// triggered it, not one generic message for both.
export default function useTabSwitchGuard(active, onViolation) {
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
  }, [active, onViolation]);
}
