import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useExamSession } from '../../features/exam/examSessionContext';
import { isRunningInSeb } from '../../features/exam/seb/sebDetection';
import { configUrl, sebLaunchUrl } from '../../features/exam/seb/sebLaunch';
import BrandHeader from '../../components/layout/BrandHeader';
import BrandFooter from '../../components/layout/BrandFooter';

const SEB_DOWNLOAD_URL = 'https://safeexambrowser.org/download_en.html';

// Sits between ExamVerify and ExamCameraPermission on a fresh start only - a resume (an
// in-progress attempt reopening its link) skips straight to /exam today and this screen is
// never part of that path, same as camera/fullscreen/instructions/identity already aren't.
//
// Safe Exam Browser is mandatory here - deliberately no "continue in a regular browser" escape
// hatch. There is no reliable way for JavaScript to know whether the seb:// link below actually
// launched an installed application (a real browser limitation, not something to work around),
// so a candidate who can't get it running has no way past this screen.
//
// Two steps rather than one dense page: get the application installed first, THEN offer
// launching it - putting "Launch"/"Download config" before a candidate has SEB at all is a dead
// click (the OS has nothing to hand the request to), so the download step comes first and is
// its own screen. "step" is plain component state, not a route - nothing downstream needs to
// know which sub-step a candidate was on, so it doesn't belong in ExamSessionContext or the URL.
export default function ExamSebChoice() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { instructions } = useExamSession();
  const [step, setStep] = useState('download');

  useEffect(() => {
    if (!instructions) {
      navigate(`/t/${token}`, { replace: true });
      return;
    }
    // Already inside real SEB (reached this URL directly, or came back to it) - both steps'
    // questions are moot, move on exactly as finishing them would.
    if (isRunningInSeb()) {
      navigate(`/t/${token}/camera`, { replace: true });
    }
  }, [instructions, navigate, token]);

  if (!instructions) return null;

  if (step === 'download') {
    return (
      <div className="app-shell">
        <BrandHeader roleCode="candidate" />
        <div className="auth-shell">
          <div className="auth-card" style={{ textAlign: 'center' }}>
            <h3>Step 1: Get Safe Exam Browser</h3>
            <div className="auth-sub">
              This assessment must be taken inside Safe Exam Browser — a free lockdown browser
              that keeps other applications and notifications from reaching you for the
              duration of the exam. Download and install it now if you don't already have it.
            </div>

            <a
              className="btn primary block"
              href={SEB_DOWNLOAD_URL}
              target="_blank"
              rel="noopener noreferrer"
            >
              Download Safe Exam Browser
            </a>
            <div className="auth-sub" style={{ fontSize: 11.5, margin: '8px 0 20px' }}>
              Opens safeexambrowser.org in a new tab. Once it's installed, come back here.
            </div>

            <button className="btn block" type="button" onClick={() => setStep('launch')}>
              I have Safe Exam Browser installed - Continue
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
          <h3>Step 2: Launch Safe Exam Browser</h3>
          <div className="auth-sub">
            Launch Safe Exam Browser to continue into your assessment.
          </div>

          <a className="btn primary block" href={sebLaunchUrl(token)}>
            Launch Safe Exam Browser
          </a>
          <div className="auth-sub" style={{ fontSize: 11.5, margin: '8px 0 20px' }}>
            If nothing happened,{' '}
            <a className="link-text" href={configUrl(token)}>
              download the configuration file
            </a>{' '}
            instead and open it manually - it will take you straight into this assessment.
          </div>

          <button className="btn block" type="button" onClick={() => setStep('download')}>
            Back
          </button>
        </div>
      </div>
      <BrandFooter roleCode="candidate" />
    </div>
  );
}
