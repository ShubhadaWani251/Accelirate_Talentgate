import { useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useExamSession } from '../../features/exam/examSessionContext';
import { isRunningInSeb } from '../../features/exam/seb/sebDetection';
import { configUrl, sebLaunchUrl } from '../../features/exam/seb/sebLaunch';
import BrandHeader from '../../components/layout/BrandHeader';
import BrandFooter from '../../components/layout/BrandFooter';

// Sits between ExamVerify and ExamCameraPermission on a fresh start only - a resume (an
// in-progress attempt reopening its link) skips straight to /exam today and this screen is
// never part of that path, same as camera/fullscreen/instructions/identity already aren't.
//
// "Continue without Safe Exam Browser" is always visible and never disabled: there is no
// reliable way for JavaScript to know whether the seb:// link below actually launched an
// installed application - that's a real browser limitation, not something to work around - so
// the only honest choice is offering the fallback immediately rather than making a candidate
// wait out a guess.
export default function ExamSebChoice() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { instructions } = useExamSession();

  useEffect(() => {
    if (!instructions) {
      navigate(`/t/${token}`, { replace: true });
      return;
    }
    // Already inside real SEB (reached this URL directly, or came back to it) - the question
    // below no longer applies, move on exactly as choosing "Launch" would.
    if (isRunningInSeb()) {
      navigate(`/t/${token}/camera`, { replace: true });
    }
  }, [instructions, navigate, token]);

  function onContinueInBrowser() {
    navigate(`/t/${token}/camera`);
  }

  if (!instructions) return null;

  return (
    <div className="app-shell">
      <BrandHeader roleCode="candidate" />
      <div className="auth-shell">
        <div className="auth-card" style={{ textAlign: 'center' }}>
          <h3>Use Safe Exam Browser</h3>
          <div className="auth-sub">
            This assessment is best taken inside Safe Exam Browser — a free lockdown browser
            that keeps other applications and notifications from reaching you for the duration
            of the exam. If you're able to install it, we recommend doing so now.
          </div>

          <a className="btn primary block" href={sebLaunchUrl(token)}>
            Launch Safe Exam Browser
          </a>
          <div className="auth-sub" style={{ fontSize: 11.5, margin: '8px 0 20px' }}>
            If it doesn't open within a few seconds, use the option below instead. Already have
            it installed but nothing happened?{' '}
            <a className="link-text" href={configUrl(token)}>
              Download the configuration file
            </a>{' '}
            and open it manually.
            <br />
            Don't have Safe Exam Browser yet?{' '}
            <a
              className="link-text"
              href="https://safeexambrowser.org/download_en.html"
              target="_blank"
              rel="noopener noreferrer"
            >
              Get it here
            </a>
            , then come back to this page.
          </div>

          <button className="btn block" type="button" onClick={onContinueInBrowser}>
            Continue without Safe Exam Browser
          </button>
        </div>
      </div>
      <BrandFooter roleCode="candidate" />
    </div>
  );
}
