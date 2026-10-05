import { LuMenu } from 'react-icons/lu';

const ROLE_LABELS = {
  admin: 'Administrator Portal',
  ta: 'Staffing User Portal',
  candidate: 'Candidate Exam Portal',
};

// `children` is an optional right-hand slot, filled only by ProtectedLayout (with the signed-in
// account and Logout). It is a slot rather than something this component renders for itself
// because the same header sits above the candidate exam portal, the login screen and the legal
// pages - none of which have an account to show or a session to end.
//
// `onToggleNav` is the same arrangement for the left: the button only exists when a caller
// passes a handler, so the twenty-odd screens with no sidebar don't render a control that would
// toggle nothing. ProtectedLayout owns the state, because the header and the sidebar are
// siblings and neither can hold it for the other.
export default function BrandHeader({ roleCode, children, onToggleNav, navOpen = false }) {
  return (
    <header className="brand-header">
      <div className="brand-left">
        {onToggleNav && (
          <button
            type="button"
            className="brand-nav-toggle"
            onClick={onToggleNav}
            aria-expanded={navOpen}
            aria-controls="app-sidebar"
            aria-label={navOpen ? 'Hide navigation menu' : 'Show navigation menu'}
          >
            <LuMenu aria-hidden="true" />
          </button>
        )}
        <img src="/favicon-48.png" alt="" className="brand-logo" />
        <div className="brand-name">
          Accelirate TalentGate
          <div className="brand-tagline">Candidate Evaluation Platform</div>
        </div>
      </div>
      <div className="brand-right">
        {roleCode && <span className="brand-role-badge">{ROLE_LABELS[roleCode] || roleCode}</span>}
        {children}
      </div>
    </header>
  );
}
