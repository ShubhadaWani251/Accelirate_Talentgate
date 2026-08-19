import { useEffect, useState } from 'react';
import { FULLSCREEN_SUPPORTED, enterFullscreen, isFullscreen } from './fullscreen';
import BrandHeader from '../../../components/layout/BrandHeader';
import BrandFooter from '../../../components/layout/BrandFooter';

// Browsers drop full-screen mode on their own the moment a permission prompt (camera/mic) needs
// to show - real, deliberate browser security behavior to stop a full-screen page from spoofing
// trusted UI, not something any site's JS can override. This wraps every screen after the initial
// full-screen gate so the candidate can't reach instructions, identity capture, or anything past
// it without full-screen active - blocking progress rather than terminating, since no ExamAttempt
// exists yet at these steps for there to be anything to terminate.
export default function RequireFullscreen({ children }) {
  const [active, setActive] = useState(!FULLSCREEN_SUPPORTED || isFullscreen());
  const [retrying, setRetrying] = useState(false);

  useEffect(() => {
    if (!FULLSCREEN_SUPPORTED) return undefined;
    function sync() {
      setActive(isFullscreen());
    }
    // Re-read on mount as well as on every change: the browser can drop full-screen in the gap
    // between this component's first render and this listener attaching (exactly what happens
    // when the camera/mic permission prompt closes as the next screen mounts), and that change
    // would otherwise never be observed - leaving the gate hidden while full-screen is off.
    sync();
    document.addEventListener('fullscreenchange', sync);
    return () => document.removeEventListener('fullscreenchange', sync);
  }, []);

  async function onReenter() {
    setRetrying(true);
    const ok = await enterFullscreen();
    setRetrying(false);
    // Read the real state rather than trusting the event alone - avoids a stuck gate on a browser
    // that fires fullscreenchange inconsistently.
    setActive(ok || isFullscreen());
  }

  if (active) return children;

  return (
    <div className="app-shell">
      <BrandHeader roleCode="candidate" />
      <div className="auth-shell">
        <div className="auth-card" style={{ textAlign: 'center' }}>
          <h3>Return to Full-Screen</h3>
          <div className="auth-sub">
            This assessment stays in full-screen mode throughout. Click below to continue.
          </div>
          <button className="btn primary block" type="button" disabled={retrying} onClick={onReenter}>
            {retrying ? 'Returning…' : 'Return to Full-Screen'}
          </button>
        </div>
      </div>
      <BrandFooter roleCode="candidate" />
    </div>
  );
}
