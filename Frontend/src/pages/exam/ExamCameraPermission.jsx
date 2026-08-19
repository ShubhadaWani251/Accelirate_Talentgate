import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useExamSession } from '../../features/exam/ExamSessionProvider';
import useCameraStream from '../../features/exam/webcam/useCameraStream';
import BrandHeader from '../../components/layout/BrandHeader';
import BrandFooter from '../../components/layout/BrandFooter';

export default function ExamCameraPermission() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { instructions, mediaStreamRef, setNoVideo } = useExamSession();
  const { requestStream, error: cameraError } = useCameraStream();
  const [requesting, setRequesting] = useState(false);

  useEffect(() => {
    if (!instructions) navigate(`/t/${token}`, { replace: true });
  }, [instructions, navigate, token]);

  async function onAllow() {
    setRequesting(true);
    try {
      const { stream, noVideo } = await requestStream();
      mediaStreamRef.current = stream;
      setNoVideo(noVideo);
      // This step deliberately runs BEFORE full-screen is ever entered. Browsers force-exit
      // full-screen whenever a permission prompt appears (security behavior - a full-screen page
      // must not be able to spoof that trusted UI), so doing it in this order means full-screen is
      // never interrupted after the fact, rather than having to detect and recover from it.
      navigate(`/t/${token}/fullscreen`);
    } catch {
      // cameraError below renders the failure state - nothing further to do here.
    } finally {
      setRequesting(false);
    }
  }

  if (!instructions) return null;

  if (cameraError) {
    return (
      <div className="app-shell">
        <BrandHeader roleCode="candidate" />
        <div className="auth-shell">
          <div className="auth-card">
            <h3>Camera Access Required</h3>
            <div className="auth-sub">
              This assessment requires camera and microphone access for identity verification and
              proctoring. Please allow access in your browser and try again.
            </div>
            <div className="alert error" style={{ fontFamily: 'monospace', fontSize: 11.5 }}>
              {cameraError.name}: {cameraError.message}
            </div>
            <button className="btn primary block" type="button" onClick={() => window.location.reload()}>
              Try Again
            </button>
          </div>
        </div>
        <BrandFooter roleCode="candidate" />
      </div>
    );
  }

  return (
    <div className="app-shell">
      <BrandHeader roleCode="candidate" />
      <div className="auth-shell">
        <div className="auth-card" style={{ textAlign: 'center' }}>
          <h3>Camera &amp; Microphone Access</h3>
          <div className="auth-sub">
            This assessment needs your camera and microphone for identity verification and
            continuous proctoring. You'll be asked by your browser to allow access.
          </div>
          <button className="btn primary block" type="button" disabled={requesting} onClick={onAllow}>
            {requesting ? 'Requesting…' : 'Allow Camera & Microphone Access'}
          </button>
        </div>
      </div>
      <BrandFooter roleCode="candidate" />
    </div>
  );
}
