import { useCallback, useState } from 'react';

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
        'Camera access is unavailable on this page. This usually means the page was opened over ' +
        'plain HTTP on an address other than "localhost" (e.g. a LAN IP) - browsers only allow ' +
        'camera/mic access on HTTPS or on localhost itself.'
      );
      err.name = 'SecureContextUnavailable';
      setError(err);
      throw err;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      return { stream, noVideo: false };
    } catch (err) {
      // Dev-only convenience: a test machine with no working webcam (or a phantom/disconnected
      // one - see Windows Device Manager's CM_PROB_PHANTOM) can still exercise the rest of the
      // exam flow using audio only. import.meta.env.DEV is statically false in a production
      // build, so this whole branch is dead code once built - it can never reach a real
      // candidate, only someone running `npm run dev` locally.
      if (import.meta.env.DEV) {
        try {
          const stream = await navigator.mediaDevices.getUserMedia({ video: false, audio: true });
          return { stream, noVideo: true };
        } catch {
          // Audio-only also failed - fall through to reporting the original error below.
        }
      }
      setError(err);
      throw err;
    }
  }, []);

  return { requestStream, error };
}
