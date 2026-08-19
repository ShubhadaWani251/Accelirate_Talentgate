import { useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useExamSession } from '../../features/exam/ExamSessionProvider';
import { FULLSCREEN_SUPPORTED, enterFullscreen } from '../../features/exam/proctoring/fullscreen';
import BrandHeader from '../../components/layout/BrandHeader';
import BrandFooter from '../../components/layout/BrandFooter';

// Full-screen has to start from a real user gesture (requestFullscreen() is rejected otherwise),
// so this screen exists specifically to be that click.
//
// It runs AFTER camera/mic permission on purpose: browsers force-exit full-screen whenever a
// permission prompt appears, so granting first means full-screen is never interrupted once
// entered. Everything from here on (instructions, identity capture, the exam) stays full-screen.
export default function ExamFullscreenGate() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { instructions, mediaStreamRef } = useExamSession();

  useEffect(() => {
    if (!instructions) {
      navigate(`/t/${token}`, { replace: true });
      return;
    }
    // No stream means the permission step was skipped (direct navigation or a reload) - send them
    // back, since granting it later would drop full-screen right after it was entered.
    if (!mediaStreamRef.current) {
      navigate(`/t/${token}/camera`, { replace: true });
      return;
    }
    // Browser doesn't support the Fullscreen API at all (rare) - move on rather than stranding
    // the candidate on a button that can't do anything.
    if (!FULLSCREEN_SUPPORTED) {
      navigate(`/t/${token}/instructions`, { replace: true });
    }
  }, [instructions, navigate, token, mediaStreamRef]);

  async function onContinue() {
    // Bounded by enterFullscreen() so a request that never settles can't strand the candidate
    // here. Proceeding even when full-screen didn't take is deliberate - RequireFullscreen on
    // the following screens blocks progress until it does, so this can't skip the requirement.
    await enterFullscreen();
    navigate(`/t/${token}/instructions`);
  }

  if (!instructions || !mediaStreamRef.current || !FULLSCREEN_SUPPORTED) return null;

  return (
    <div className="app-shell">
      <BrandHeader roleCode="candidate" />
      <div className="auth-shell">
        <div className="auth-card" style={{ textAlign: 'center' }}>
          <h3>Continue to Full-Screen Mode</h3>
          <div className="auth-sub">
            Camera and microphone access is granted. The assessment now runs in full-screen mode
            for its full duration — through the instructions, identity verification, and the exam
            itself. Exiting full-screen once the exam begins will end your attempt automatically.
          </div>
          <button className="btn primary block" type="button" onClick={onContinue}>
            Continue to Full-Screen Mode
          </button>
        </div>
      </div>
      <BrandFooter roleCode="candidate" />
    </div>
  );
}
