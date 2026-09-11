import { useEffect, useRef, useState } from 'react';
import { isBlockedFrame, statsFromVideo } from './frameCheck';

// Live camera preview + a snapshot-to-Blob capture button. Used twice on the identity-capture
// screen (Aadhaar Card, then live face) sharing the same underlying stream.
//
// A captured shot is shown back to the candidate and can be retaken. Both halves matter: a
// blurred ID or a half-out-of-frame face is the TA's only identity evidence later, and before
// this the first capture was final - the button simply went dead and read "Captured", so a
// candidate who could see their photo was unusable had no way to fix it.
//
// Four props beyond the original stream/label/hint/onCapture/captured, all optional so the
// face-photo card's usage stays exactly as simple as before:
//   verifying      - captured, but a server verdict is still in flight (Aadhaar only)
//   feedback       - { tone: 'green'|'red'|'amber', text } | null - null keeps the original,
//                    always-green "captured" banner (used whenever there's no real verification
//                    outcome to report, i.e. the face-photo card, and the Aadhaar card whenever
//                    AADHAAR_VERIFICATION_ENABLED is off)
//   retakeDisabled - hides the Retake button once matched or retries are exhausted
//   liveHint       - { tone: 'green'|'gray', text } | null - shown above the LIVE preview only
//   captureBlocked - true disables the Capture button entirely (e.g. no face detected yet) -
//                    unlike liveHint (informational), this actually prevents the click
export default function PhotoCapture({
  stream, label, hint, onCapture, captured, verifying, feedback, retakeDisabled, liveHint,
  captureBlocked,
}) {
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
    if (!video || captureBlocked) return;

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

      {!captured && liveHint && (
        <div style={{ fontSize: 11.5, marginBottom: 6, color: liveHint.tone === 'green' ? 'var(--green)' : 'var(--muted)' }}>
          {liveHint.tone === 'green' ? '● ' : '○ '}{liveHint.text}
        </div>
      )}

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
          {verifying ? (
            <div className="alert" style={{ marginTop: 8 }}>
              Verifying {label}…
            </div>
          ) : feedback ? (
            <div className={`alert ${feedback.tone}`} style={{ marginTop: 8 }}>
              {feedback.text}
            </div>
          ) : (
            <div className="alert success" style={{ marginTop: 8 }}>
              ✔ {label} captured — check it is clear and readable, or retake it.
            </div>
          )}
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
          !retakeDisabled && (
            <button type="button" className="btn" onClick={retake} disabled={verifying}>
              ↻ Retake {label}
            </button>
          )
        ) : (
          <button type="button" className="btn primary" onClick={capture} disabled={captureBlocked}>
            {captureBlocked ? `Waiting — ${liveHint?.text ?? 'position yourself in frame'}` : `Capture ${label}`}
          </button>
        )}
      </div>
    </div>
  );
}
