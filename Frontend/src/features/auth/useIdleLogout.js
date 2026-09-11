import { useEffect, useRef } from 'react';

const IDLE_LIMIT_MS = 60 * 60 * 1000; // 1 hour
// Checked periodically rather than resetting a setTimeout on every event: mousemove alone can
// fire dozens of times a second, and thrashing a fresh timer that often is needless churn for a
// boundary this coarse - a 1-hour idle limit easily tolerates this interval's own latency.
const CHECK_INTERVAL_MS = 30 * 1000;
const ACTIVITY_EVENTS = ['mousemove', 'mousedown', 'keydown', 'scroll', 'touchstart', 'wheel'];

/**
 * Calls `onIdle` once, after IDLE_LIMIT_MS with no mouse/keyboard/scroll/touch activity anywhere
 * on the page. Meant to be mounted exactly once, at the root of the protected staff/admin area
 * (see ProtectedLayout.jsx) - never on the login screen (nothing to time out yet) and never in
 * the candidate exam portal, which has its own, much more deliberate proctoring/session design
 * (warnings, fullscreen/tab-switch enforcement, a server-authoritative exam timer) that a generic
 * inactivity logout must not interfere with - a candidate reading a hard question for over an
 * hour without touching the mouse is normal there, not something to log out for.
 *
 * `onIdle` is expected to be referentially stable (wrap it in useCallback at the call site) -
 * this effect only sets up listeners/the interval once per mount, not on every render.
 */
export default function useIdleLogout(onIdle) {
  // Seeded inside the effect below, not here - Date.now() is an impure call and reading it
  // during render (even just as a useRef initializer) breaks React's purity rules.
  const lastActivityRef = useRef(null);
  const firedRef = useRef(false);

  useEffect(() => {
    function markActive() {
      lastActivityRef.current = Date.now();
    }
    markActive();
    ACTIVITY_EVENTS.forEach((event) => window.addEventListener(event, markActive, { passive: true }));

    const intervalId = setInterval(() => {
      if (!firedRef.current && Date.now() - lastActivityRef.current >= IDLE_LIMIT_MS) {
        // Guards against firing more than once - onIdle is async (revokes the refresh token
        // server-side), and this interval would otherwise keep ticking during that call.
        firedRef.current = true;
        onIdle();
      }
    }, CHECK_INTERVAL_MS);

    return () => {
      ACTIVITY_EVENTS.forEach((event) => window.removeEventListener(event, markActive));
      clearInterval(intervalId);
    };
  }, [onIdle]);
}
