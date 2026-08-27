import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import * as examApi from '../../api/examApi';
import { useExamSession } from '../../features/exam/examSessionContext';
import RequireFullscreen from '../../features/exam/proctoring/RequireFullscreen';
import PhotoCapture from '../../features/exam/webcam/PhotoCapture';
import useDisplayGuard from '../../features/exam/proctoring/useDisplayGuard';
import BrandHeader from '../../components/layout/BrandHeader';
import BrandFooter from '../../components/layout/BrandFooter';
import { ButtonSpinner } from '../../components/loading/Spinner';

// Dev-only convenience for a test machine with no working webcam (see useCameraStream.js) -
// stands in for the two required photos so the rest of the flow can still be exercised. Never
// reachable in a production build.
function createPlaceholderPhotoBlob(label) {
  return new Promise((resolve) => {
    const canvas = document.createElement('canvas');
    canvas.width = 320;
    canvas.height = 240;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#111';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#fff';
    ctx.font = '16px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('TEST — NO CAMERA', canvas.width / 2, canvas.height / 2 - 10);
    ctx.fillText(label, canvas.width / 2, canvas.height / 2 + 14);
    canvas.toBlob((blob) => resolve(blob), 'image/jpeg', 0.9);
  });
}

export default function ExamIdVerify() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { instructions, applyAttemptToken, setSessionState, mediaStreamRef, noVideo } = useExamSession();
  const [idPhoto, setIdPhoto] = useState(null);
  const [facePhoto, setFacePhoto] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  // Watched continuously, so plugging a monitor in after this screen loads is caught too.
  const { extended: extraDisplay } = useDisplayGuard(true);
  const [submitError, setSubmitError] = useState('');

  const stream = mediaStreamRef.current;

  useEffect(() => {
    if (!instructions) {
      navigate(`/t/${token}`, { replace: true });
      return;
    }
    // Camera/mic access was already granted on the dedicated permission screen - a missing
    // stream here means that step was skipped (direct navigation, reload) rather than denied.
    if (!stream) {
      navigate(`/t/${token}/camera`, { replace: true });
      return;
    }
    if (noVideo) {
      Promise.all([
        createPlaceholderPhotoBlob('Government ID'),
        createPlaceholderPhotoBlob('Live Face Photo'),
      ]).then(([idBlob, faceBlob]) => {
        setIdPhoto(idBlob);
        setFacePhoto(faceBlob);
      });
    }
  }, [instructions, navigate, token, stream, noVideo]);

  async function onStartAssessment() {
    setSubmitError('');
    setSubmitting(true);
    try {
      const data = await examApi.submitIdentity(token, idPhoto, facePhoto);
      applyAttemptToken(data.attempt_token, token);
      setSessionState({ remaining_seconds: data.remaining_seconds, sections: data.sections });
      navigate(`/t/${token}/exam`);
    } catch (err) {
      setSubmitError(err.response?.data?.detail || 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  if (!instructions || !stream) return null;

  const bothCaptured = Boolean(idPhoto && facePhoto);

  return (
    <RequireFullscreen>
    <div className="app-shell">
      <BrandHeader roleCode="candidate" />
      <div className="auth-shell">
        <div className="auth-card" style={{ maxWidth: 640 }}>
          <h3>Identity Verification</h3>
          <div className="auth-sub">Capture your government ID, then a live photo of your face.</div>

          {submitError && <div className="alert error">{submitError}</div>}

          {noVideo ? (
            bothCaptured ? (
              <div className="alert">
                🧪 Dev mode: no working camera detected on this machine, so placeholder photos are
                being used instead of real captures. This path only exists in local dev builds -
                a real candidate always captures both photos for real.
              </div>
            ) : (
              <div className="auth-sub">Preparing test photos…</div>
            )
          ) : (
            <div style={{ display: 'grid', gap: 14 }}>
              <PhotoCapture
                stream={stream}
                label="Government ID"
                hint="Aadhaar / PAN / Passport / Driving Licence"
                captured={idPhoto}
                onCapture={setIdPhoto}
              />
              <PhotoCapture
                stream={stream}
                label="Live Face Photo"
                hint="Center your face in the frame"
                captured={facePhoto}
                onCapture={setFacePhoto}
              />
            </div>
          )}

          {/* A second display is the setup that makes screen sharing useful for cheating,
              and unlike the sharing itself it IS detectable. Blocking here rather than after
              the clock starts, so the candidate can unplug and continue without losing time. */}
          {extraDisplay && (
            <div className="alert error" style={{ marginTop: 14 }}>
              <b>More than one display detected.</b> The assessment must be taken on a single
              screen. Please disconnect any additional monitor, projector or screen-sharing
              session, then this message will clear on its own.
            </div>
          )}

          <button
            className="btn primary block"
            type="button"
            style={{ marginTop: 14 }}
            disabled={!bothCaptured || submitting || extraDisplay}
            onClick={onStartAssessment}
          >
            <ButtonSpinner loading={submitting}>Start Exam</ButtonSpinner>
          </button>
        </div>
      </div>
      <BrandFooter roleCode="candidate" />
    </div>
    </RequireFullscreen>
  );
}
