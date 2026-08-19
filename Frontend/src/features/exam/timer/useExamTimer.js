import { useEffect, useRef, useState } from 'react';

function formatRemaining(totalSeconds) {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

// Cosmetic countdown only - the server (services/exam_session.remaining_seconds) is the real
// authority and re-checks the deadline on every write, so a tampered client clock can't extend
// the exam. `onExpire` should be a stable callback (useCallback) - it's an effect dependency.
//
// `active` gates the interval entirely. It must default to false-safe behavior: without it, a
// hook mounted before the exam has begun (remaining = 0) would tick once and immediately fire
// onExpire, auto-submitting a blank exam.
export default function useExamTimer(initialSeconds, onExpire, active = true) {
  const [remaining, setRemaining] = useState(initialSeconds);
  const expiredRef = useRef(false);

  useEffect(() => {
    setRemaining(initialSeconds);
    expiredRef.current = false;
  }, [initialSeconds]);

  useEffect(() => {
    if (!active) return undefined;
    const interval = setInterval(() => {
      setRemaining((prev) => {
        if (prev <= 1) {
          clearInterval(interval);
          if (!expiredRef.current) {
            expiredRef.current = true;
            onExpire();
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [onExpire, active]);

  return { remaining, formatted: formatRemaining(remaining) };
}
