import { useNavigate } from 'react-router-dom';
import BrandHeader from '../../components/layout/BrandHeader';
import BrandFooter from '../../components/layout/BrandFooter';

// Reachable from the footer on every screen - staff console and candidate exam portal alike -
// so this has no auth requirement and no assumed role. Content below is split into the two
// audiences that actually land here.
export default function HelpSupport() {
  const navigate = useNavigate();

  return (
    <div className="app-shell">
      <BrandHeader />
      <div className="auth-shell">
        <div className="auth-card" style={{ maxWidth: 640 }}>
          <h3>Help &amp; Support</h3>
          <div className="auth-sub">Common issues and how to resolve them</div>

          <div className="card">
            <div className="box-label">For Candidates</div>
            <div style={{ fontSize: 12.5, lineHeight: 1.9 }}>
              <b>My assessment link says it's invalid or expired.</b><br />
              Use the exact link from your invitation email rather than a copy that may have lost
              part of the address. Each link works once and expires at a fixed time - if it has
              expired, reply to your invitation email or contact the Staffing team who invited you
              for a new one.
              <br /><br />
              <b>My camera or microphone won't start.</b><br />
              When your browser asks for camera/microphone permission, choose Allow - the
              assessment cannot begin without both. If you accidentally blocked it, look for a
              camera icon in your browser's address bar to change the permission, then reload the
              page.
              <br /><br />
              <b>Can I leave the assessment tab or window?</b><br />
              No. Once the assessment begins you must stay on that tab, in full-screen, for the
              whole duration - switching tabs, minimizing, or exiting full-screen ends your
              attempt after one warning. This is stated on the instructions screen before you
              begin.
              <br /><br />
              <b>My camera was flagged as off or covered.</b><br />
              Keep your camera on and unobstructed for the entire assessment - check for a privacy
              shutter or another application (Teams, Zoom) using the camera.
              <br /><br />
              <b>Something else went wrong during my assessment.</b><br />
              Contact the Staffing team who sent your invitation - they can see what happened on
              their end and advise on next steps.
            </div>
          </div>

          <div className="card">
            <div className="box-label">For Staffing Users &amp; Administrators</div>
            <div style={{ fontSize: 12.5, lineHeight: 1.9 }}>
              <b>I forgot my password.</b><br />
              Use "Forgot password?" on the login screen - a one-time code is emailed to your
              corporate address to reset it.
              <br /><br />
              <b>A candidate says their invitation link doesn't work.</b><br />
              Open the candidate's record and check their email status. A failed or queued send
              can be resent from there; an expired link needs a fresh invite.
              <br /><br />
              <b>I need something not covered here.</b><br />
              Reach out to your system administrator or IT support through your usual internal
              channel.
            </div>
          </div>

          <button className="btn block" type="button" onClick={() => navigate(-1)}>
            Back
          </button>
        </div>
      </div>
      <BrandFooter />
    </div>
  );
}
