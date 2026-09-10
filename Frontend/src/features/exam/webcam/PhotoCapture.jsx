import { useEffect, useRef, useState } from 'react';
import { isBlockedFrame, statsFromVideo } from './frameCheck';

// Live camera preview + a snapshot-to-Blob capture button. Used twice on the identity-capture
// screen (government ID, then live face) sharing the same underlying stream.
//
// A captured shot is shown back to the candidate and can be retaken. Both halves matter: a
// blurred ID or a half-out-of-frame face is the TA's only identity evidence later, and before
// this the first capture was final - the button simply went dead and read "Captured", so a
// candidate who could see their photo was unusable had no way to fix it.
export default function PhotoCapture({ stream, label, hint, onCapture, captured }) {
  const videoRef = useRef(null);
  const [blankError, setBlankError] = useState('');
  const [previewUrl, setPreviewUrl] = useState(null);

  useEffect(() => {
    if (videoRef.current && stream) {
      videoRef.current.srcObject = stream;
    }
  }, [stream, captured]);

  // Object URLs are revoked when the blob changes or the component unmounts - without this each
  // retake leaks the previous image for the life of the page.
  useEffect(() => {
    if (!captured) {
      setPreviewUrl(null);
      return undefined;
    }
    const url = URL.createObjectURL(captured);
    setPreviewUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [captured]);

  function capture() {
    const video = videoRef.current;
    if (!video) return;

    // Re-checked at capture time, not just once on the permission screen: otherwise a candidate
    // could open the shutter to pass that check and close it again before capturing, leaving the
    // TA with two black rectangles as their only identity evidence.
    if (isBlockedFrame(statsFromVideo(video))) {
      setBlankError(
        'No image is coming through - please open your camera\'s privacy shutter (or remove any '
        + 'cover over the lens) and capture again.'
      );
      return;
    }
    setBlankError('');

    const canvas = document.createElement('canvas');
    canvas.width = video.videoWidth || 640;
    canvas.height = video.videoHeight || 480;
    canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      if (blob) onCapture(blob);
    }, 'image/jpeg', 0.9);
  }

  function retake() {
    // Clearing the blob swings this card back to the live preview; the parent holds the state,
    // so nothing is uploaded until Start Exam is pressed and a retake costs nothing.
    setBlankError('');
    onCapture(null);
  }

  return (
    <div className="card">
      <div className="box-label">{label}</div>
      {hint && <div style={{ fontSize: 11.5, color: 'var(--muted)', marginBottom: 8 }}>{hint}</div>}

      {captured ? (
        <>
          {/* Shown back to the candidate so they can judge it before committing. */}
          {previewUrl && (
            <img
              src={previewUrl}
              alt={`${label} preview`}
              style={{ width: '100%', borderRadius: 8, background: '#111', display: 'block' }}
            />
          )}
          <div className="alert success" style={{ marginTop: 8 }}>
            ✔ {label} captured — check it is clear and readable, or retake it.
          </div>
        </>
      ) : (
        <video
          ref={videoRef}
          autoPlay
          playsInline
          muted
          style={{ width: '100%', borderRadius: 8, background: '#111', display: 'block' }}
        />
      )}

      {blankError && <div className="alert error" style={{ marginTop: 8 }}>{blankError}</div>}

      <div className="btn-row" style={{ marginTop: 10, display: 'flex', gap: 8 }}>
        {captured ? (
          <button type="button" className="btn" onClick={retake}>
            ↻ Retake {label}
          </button>
        ) : (
          <button type="button" className="btn primary" onClick={capture}>
            Capture {label}
          </button>
        )}
      </div>
    </div>
  );
}
