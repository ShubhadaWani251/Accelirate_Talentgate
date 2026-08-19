import { useCallback, useState } from 'react';

// Dev escape hatch for a machine with no working webcam, now requiring an EXPLICIT opt-in
// (?devNoCamera=1) rather than triggering automatically. It used to fall back silently, which
// meant "no camera at all" looked indistinguishable from a successful start - masking the very
// thing that must be caught: an exam must never begin without a working, unobstructed camera.
function devNoCameraRequested() {
  if (!import.meta.env.DEV) return false;
  try {
    return new URLSearchParams(window.location.search).get('devNoCamera') === '1';
  } catch {
    return false;
  }
}

export default function useCameraStream() {
  const [error, setError] = useState(null);

  const requestStream = useCallback(async () => {
    setError(null);
    // navigator.mediaDevices is only defined in a secure context (HTTPS, or http://localhost) -
    // on plain HTTP against a LAN IP/hostname it's undefined entirely, which throws before the
    // browser ever gets a chance to show its native permission prompt. Surfacing that distinctly
    // from an actual camera/mic denial saves a lot of guessing when this happens.
    if (!navigator.mediaDevices?.getUserMedia) {
      const err = new Error(
        'Camera access is unavailable on this page. This usually means the page was opened over '
        + 'plain HTTP on an address other than "localhost" (e.g. a LAN IP) - browsers only allow '
        + 'camera/mic access on HTTPS or on localhost itself.'
      );
      err.name = 'SecureContextUnavailable';
      setError(err);
      throw err;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      return { stream, noVideo: false };
    } catch (err) {
      if (devNoCameraRequested()) {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ video: false, audio: true });
          return { stream, noVideo: true };
        } catch {
          // Audio-only also failed - report the original camera error below.
        }
      }
      setError(err);
      throw err;
    }
  }, []);

  return { requestStream, error };
}
