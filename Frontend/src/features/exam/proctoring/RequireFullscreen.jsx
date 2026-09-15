import { useEffect, useState } from 'react';
import { FULLSCREEN_SUPPORTED, enterFullscreen, isFullscreen } from './fullscreen';
import { isNativeDialogOpen } from './nativeDialogGuard';
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
      // A native OS dialog (the Aadhaar upload's file picker) also drops full-screen, same as a
      // permission prompt - but that one IS expected and temporary, not a real exit, so showing
      // this gate for it would unmount the very <input> the dialog is about to hand a file back
      // to. See nativeDialogGuard.js for the full story. talentgate:nativedialogclose (below)
      // re-runs this once the suppression lifts, so the real state still gets picked up.
      if (isNativeDialogOpen()) return;
      setActive(isFullscreen());
    }
    // Re-read on mount as well as on every change: the browser can drop full-screen in the gap
    // between this component's first render and this listener attaching (exactly what happens
    // when the camera/mic permission prompt closes as the next screen mounts), and that change
    // would otherwise never be observed - leaving the gate hidden while full-screen is off.
    sync();
    document.addEventListener('fullscreenchange', sync);
    window.addEventListener('talentgate:nativedialogclose', sync);
    return () => {
      document.removeEventListener('fullscreenchange', sync);
      window.removeEventListener('talentgate:nativedialogclose', sync);
    };
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
