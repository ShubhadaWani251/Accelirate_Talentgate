import { useEffect, useRef, useState } from 'react';
import { isBlockedFrame, statsFromVideo } from './frameCheck';
import { beginNativeDialog } from '../proctoring/nativeDialogGuard';

// Mirrors the server's own allowlist and size cap exactly - Backend/api/services/
// image_validation.py (ALLOWED_IMAGE_CONTENT_TYPES | ALLOWED_DOCUMENT_CONTENT_TYPES, and
// MAX_PHOTO_SIZE_BYTES). That file stays the security boundary; this is only here so a candidate
// finds out before an upload rather than after one. Keep the two in step: anything accepted here
// and refused there is a candidate told "fine" and then "no".
//
// The `accept` attribute alone does not do this job. It filters what the file picker shows by
// default, but every OS picker offers an "All Files" escape, so an unsupported file reached the
// server and came back as a failed upload with no clear reason - which is exactly what this
// catches now.
const UPLOAD_CONTENT_TYPES = ['image/jpeg', 'image/png'];
const UPLOAD_MAX_BYTES = 5 * 1024 * 1024;

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
//   allowUpload    - true also offers "upload a file instead of the live camera" (Aadhaar Card
//                    only - a live face photo must come from the camera, not a file, or the
//                    liveness check it feeds has nothing to check)
export default function PhotoCapture({
  stream, label, hint, onCapture, captured, verifying, feedback, retakeDisabled, liveHint,
  captureBlocked, allowUpload,
}) {
  const videoRef = useRef(null);
  const [captureError, setCaptureError] = useState('');
  const [previewUrl, setPreviewUrl] = useState(null);
  // Holds the current native-dialog end() between the upload input's onClick (which opens it)
  // and whichever of onChange/window-focus resolves it first - see nativeDialogGuard.js.
  const endUploadDialogRef = useRef(null);

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
      setCaptureError(
        'No image is coming through - please open your camera\'s privacy shutter (or remove any '
        + 'cover over the lens) and capture again.'
      );
      return;
    }
    setCaptureError('');

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
    setCaptureError('');
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

      {!captured && allowUpload && (
        <div style={{ marginTop: 8 }}>
          <div style={{ fontSize: 11.5, color: 'var(--muted)', marginBottom: 6 }}>
            Or upload your Aadhaar instead — a <b>JPG or PNG image only</b>. Make sure the
            Aadhaar number and your date of birth are both in frame; a masked card showing only
            the last 4 digits is fine. If you have an e-Aadhaar PDF, open it and take a
            screenshot or photo of the front of the card, then upload that.
          </div>
          <input
            type="file"
            // Advisory only - every OS picker offers an "All Files" escape, so onChange below
            // does the real check and Backend/api/services/image_validation.py is the boundary.
            accept="image/jpeg,image/png"
            onClick={() => {
              // Must be armed before the native dialog opens (onClick fires first) - see
              // nativeDialogGuard.js. window regaining focus is the one signal common to every
              // way the dialog can end (a file chosen, or cancelled), so that disarms it;
              // onChange below also disarms it directly, as a belt-and-braces second path.
              endUploadDialogRef.current = beginNativeDialog();
              window.addEventListener('focus', endUploadDialogRef.current, { once: true });
            }}
            onChange={(e) => {
              endUploadDialogRef.current?.();
              endUploadDialogRef.current = null;
              const file = e.target.files?.[0];
              // Reset before validating, so picking the same file twice still fires onChange -
              // a candidate who fixes nothing and retries should see the message again, not
              // silence.
              e.target.value = '';
              if (!file) return;

              // Named rather than just "invalid file": a candidate looking at their own file
              // manager needs to know which of their files is the problem and what to pick
              // instead. A bare "upload failed" leaves them retrying the same document.
              if (!UPLOAD_CONTENT_TYPES.includes(file.type)) {
                // A PDF gets its own sentence because it is the wrong file candidates are
                // likeliest to reach for - the official e-Aadhaar downloads as one - so
                // "not allowed" without telling them what to do instead would strand them.
                const isPdf = file.type === 'application/pdf'
                  || /\.pdf$/i.test(file.name);
                setCaptureError(
                  `"${file.name}" is not allowed. Only JPG, JPEG and PNG images can be `
                  + 'uploaded.'
                  + (isPdf
                    ? ' PDF files are not accepted — please open your e-Aadhaar and upload a'
                      + ' screenshot or photo of the front of the card instead.'
                    : '')
                );
                return;
              }
              if (file.size > UPLOAD_MAX_BYTES) {
                // Phone cameras clear 5MB routinely, so this is the likelier of the two to be
                // hit by somebody doing nothing wrong - hence the second way out.
                const mb = (file.size / (1024 * 1024)).toFixed(1);
                setCaptureError(
                  `"${file.name}" is ${mb}MB, and the limit is 5MB. Please upload a smaller `
                  + 'file, or photograph the card with your camera instead.'
                );
                return;
              }
              setCaptureError('');
              onCapture(file);
            }}
          />
        </div>
      )}

      {captureError && <div className="alert error" style={{ marginTop: 8 }}>{captureError}</div>}

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
