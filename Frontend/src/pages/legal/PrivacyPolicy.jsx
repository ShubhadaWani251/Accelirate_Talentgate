import { useNavigate } from 'react-router-dom';
import BrandHeader from '../../components/layout/BrandHeader';
import BrandFooter from '../../components/layout/BrandFooter';

// Reachable from the footer with no auth requirement, same as HelpSupport.
//
// The content below describes what this system actually does, sourced from the models and
// services that handle candidate data - it is not generic template legal text. It is written
// this way on purpose: a privacy notice that doesn't match real behavior is worse than none.
//
// It is NOT a substitute for legal review. This system collects candidates' Aadhaar (last 4
// digits), a government ID photo, a live face photo, and continuous audio/video during the
// exam - data with real regulatory weight (India's DPDP Act 2023 among others). Treat this as a
// factual starting draft, not Accelirate's reviewed and adopted policy, until someone with that
// authority has signed off on it.
export default function PrivacyPolicy() {
  const navigate = useNavigate();

  return (
    <div className="app-shell">
      <BrandHeader />
      <div className="auth-shell">
        <div className="auth-card" style={{ maxWidth: 680 }}>
          <h3>Privacy Notice</h3>
          <div className="auth-sub">Accelirate TalentGate - Candidate Evaluation Platform</div>

          <div className="card" style={{ borderColor: 'var(--amber, #b58900)' }}>
            <div className="box-label">Draft</div>
            <div style={{ fontSize: 12, lineHeight: 1.7 }}>
              This notice describes what this system actually collects and how it is actually
              handled, based on its current implementation. It has not been reviewed by legal or
              compliance and should not be treated as Accelirate's final, adopted policy until
              it has.
            </div>
          </div>

          <div className="card">
            <div className="box-label">What We Collect</div>
            <div style={{ fontSize: 12.5, lineHeight: 1.9 }}>
              <b>From every candidate:</b> name, email, phone number, the last 4 digits of your
              Aadhaar number (the full number is never stored), college, degree, stream,
              percentage, graduating year, and location - as submitted by the organization
              inviting you to assess.
              <br /><br />
              <b>During the assessment only:</b> a photo of a government ID, a live photo of your
              face for identity verification, and continuous audio and video recording for the
              full duration of the assessment. Your assessment answers and score are also
              recorded.
              <br /><br />
              <b>Technical data:</b> your IP address and browser identifier are logged against
              key actions (invitation sent, assessment started/submitted) for security and audit
              purposes.
            </div>
          </div>

          <div className="card">
            <div className="box-label">Why We Collect It</div>
            <div style={{ fontSize: 12.5, lineHeight: 1.9 }}>
              Solely to run the assessment you were invited to: to identify you, to verify you
              are the person taking the assessment, to score your responses, and to give the
              hiring organization a record they can review if a result is questioned.
            </div>
          </div>

          <div className="card">
            <div className="box-label">Who Can See It</div>
            <div style={{ fontSize: 12.5, lineHeight: 1.9 }}>
              Only Administrator and Staffing User accounts at the organization that invited you,
              and only through the platform itself - identity photos and the session recording
              are not public links; each is only viewable to a signed-in Staffing User or
              Administrator, and access is logged.
            </div>
          </div>

          <div className="card">
            <div className="box-label">How It's Stored</div>
            <div style={{ fontSize: 12.5, lineHeight: 1.9 }}>
              Your details are held in a private database. Identity photos and session recordings
              are held in private cloud storage with no public access - each is served through a
              link that expires after a short time, generated fresh each time it is viewed.
            </div>
          </div>

          <div className="card">
            <div className="box-label">Questions</div>
            <div style={{ fontSize: 12.5, lineHeight: 1.9 }}>
              For questions about your data, contact the Staffing team who sent your assessment
              invitation.
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
