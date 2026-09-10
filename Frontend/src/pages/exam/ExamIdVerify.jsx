import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import * as examApi from '../../api/examApi';
import { useExamSession } from '../../features/exam/examSessionContext';
import RequireFullscreen from '../../features/exam/proctoring/RequireFullscreen';
import PhotoCapture from '../../features/exam/webcam/PhotoCapture';
import useLiveFaceCheck from '../../features/exam/webcam/useLiveFaceCheck';
import { computeFaceEmbedding } from '../../features/exam/proctoring/faceEmbedding';
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

// Maps an Aadhaar capture verdict (see ExamIdentityAadhaarCaptureView / services.aadhaar) to
// PhotoCapture's feedback props - green/red/amber matches this codebase's existing
// DUPLICATE_PILL convention (Frontend/src/features/batches/ReviewStep.jsx): green=safe,
// amber=worth a look, red=needs a decision right now.
function aadhaarFeedback(verdict) {
  if (!verdict || !verdict.aadhaar_verification_enabled) {
    // Feature off (today's actual default) - null keeps PhotoCapture's original, always-green
    // "captured" banner with unlimited retakes: zero visual change from before this feature.
    return { feedback: null, retakeDisabled: false, resolved: true };
  }
  if (verdict.aadhaar_verification_status === 'match') {
    return {
      feedback: { tone: 'green', text: '✔ Aadhaar verified — this matches your registered details.' },
      retakeDisabled: true,
      resolved: true,
    };
  }
  if (verdict.aadhaar_needs_manual_review) {
    return {
      feedback: {
        tone: 'amber',
        text: "Couldn't automatically verify your Aadhaar Card after a retake — you may "
          + 'continue; this will be reviewed by the Staffing team.',
      },
      retakeDisabled: true,
      resolved: true,
    };
  }
  return {
    feedback: {
      tone: 'red',
      text: "Couldn't verify this photo against your registered Aadhaar details — please "
        + 'retake it, making sure the number is clearly visible.',
    },
    retakeDisabled: false,
    resolved: false,
  };
}

export default function ExamIdVerify() {
  const { token } = useParams();
  const navigate = useNavigate();
  const {
    instructions, applyAttemptToken, setSessionState, mediaStreamRef, noVideo, faceEmbeddingRef,
  } = useExamSession();
  const [idPhoto, setIdPhoto] = useState(null);
  const [facePhoto, setFacePhoto] = useState(null);
  const [aadhaarVerdict, setAadhaarVerdict] = useState(null);
  const [aadhaarVerifying, setAadhaarVerifying] = useState(false);
  const [aadhaarError, setAadhaarError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  // Watched continuously, so plugging a monitor in after this screen loads is caught too.
  const { extended: extraDisplay } = useDisplayGuard(true);
  const [submitError, setSubmitError] = useState('');

  const stream = mediaStreamRef.current;

  const { feedback, retakeDisabled, resolved } = noVideo
    ? { feedback: null, retakeDisabled: false, resolved: true }
    : aadhaarFeedback(aadhaarVerdict);
  // The face-photo card (and Start Exam) only reveal once the Aadhaar step above has resolved -
  // matched, verification disabled, or retries exhausted and flagged - never blocked. This is
  // what actually makes "retry before face capture" real, not just a backend rule with no UX to
  // match it.
  const aadhaarResolved = Boolean(idPhoto) && resolved;
  const bothCaptured = Boolean(idPhoto && facePhoto);

  // Hooks must run unconditionally (before any early return below), even though its result is
  // only meaningful once the Aadhaar step has resolved and the face card is actually showing.
  const { faceCount } = useLiveFaceCheck(mediaStreamRef, aadhaarResolved && !facePhoto && !noVideo);
  const liveHint = faceCount == null ? null
    : faceCount === 1 ? { tone: 'green', text: 'Face detected — good to capture' }
      : { tone: 'gray', text: faceCount === 0 ? 'No face detected yet' : 'More than one face detected' };

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
        createPlaceholderPhotoBlob('Aadhaar Card'),
        createPlaceholderPhotoBlob('Live Face Photo'),
      ]).then(([idBlob, faceBlob]) => {
        setIdPhoto(idBlob);
        setFacePhoto(faceBlob);
      });
    }
  }, [instructions, navigate, token, stream, noVideo]);

  // Baseline face embedding for useFaceIdentityGuard's continuous in-exam matching, captured once
  // at the exact moment the live face photo is taken - functionally identical to embedding the
  // captured photo itself (same instant, same pose, same lighting), but grabbed from the live
  // stream rather than the saved blob so the shared FaceLandmarker singleton (visionModels.js,
  // built in VIDEO mode for the always-running proctoring guard) never has its running mode
  // toggled for a still-image call it isn't configured for. Never fatal - a failure here just
  // leaves useFaceIdentityGuard to compute a fallback baseline later, matching this feature's
  // never-block-the-exam guarantee.
  useEffect(() => {
    if (!facePhoto || noVideo || !stream) return undefined;
    let cancelled = false;
    const video = document.createElement('video');
    video.muted = true;
    video.playsInline = true;
    video.srcObject = stream;
    video.play().catch(() => {});
    const ready = video.readyState >= 2
      ? Promise.resolve()
      : new Promise((resolve) => { video.onloadeddata = resolve; });
    ready
      .then(() => computeFaceEmbedding(video))
      .then((embedding) => {
        if (!cancelled && embedding) faceEmbeddingRef.current = embedding;
      })
      .catch(() => {});
    return () => {
      cancelled = true;
      video.srcObject = null;
    };
  }, [facePhoto, noVideo, stream, faceEmbeddingRef]);

  async function onCaptureAadhaar(blob) {
    setIdPhoto(blob);
    setAadhaarError('');
    if (!blob) {
      setAadhaarVerdict(null);
      return;
    }
    setAadhaarVerifying(true);
    try {
      setAadhaarVerdict(await examApi.captureAadhaarPhoto(token, blob));
    } catch (err) {
      setAadhaarError(err.response?.data?.detail || 'Something went wrong. Please try again.');
      setIdPhoto(null); // don't strand them on an unverified photo after a network failure
    } finally {
      setAadhaarVerifying(false);
    }
  }

  async function onStartAssessment() {
    setSubmitError('');
    setSubmitting(true);
    try {
      const data = await examApi.submitIdentity(token, facePhoto);
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

  return (
    <RequireFullscreen>
    <div className="app-shell">
      <BrandHeader roleCode="candidate" />
      <div className="auth-shell">
        <div className="auth-card" style={{ maxWidth: 640 }}>
          <h3>Identity Verification</h3>
          <div className="auth-sub">Capture your Aadhaar Card, then a live photo of your face.</div>

          {submitError && <div className="alert error">{submitError}</div>}
          {aadhaarError && <div className="alert error">{aadhaarError}</div>}

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
                label="Aadhaar Card"
                hint="Front side, showing your Aadhaar number clearly"
                captured={idPhoto}
                onCapture={onCaptureAadhaar}
                verifying={aadhaarVerifying}
                feedback={feedback}
                retakeDisabled={retakeDisabled}
              />
              {aadhaarResolved && (
                <PhotoCapture
                  stream={stream}
                  label="Live Face Photo"
                  hint="Center your face in the frame"
                  captured={facePhoto}
                  onCapture={setFacePhoto}
                  liveHint={liveHint}
                />
              )}
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
