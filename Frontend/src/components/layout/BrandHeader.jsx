const ROLE_LABELS = {
  admin: 'Administrator Portal',
  ta: 'Staffing User Portal',
  candidate: 'Candidate Exam Portal',
};

// `children` is an optional right-hand slot, filled only by ProtectedLayout (with the signed-in
// account and Logout). It is a slot rather than something this component renders for itself
// because the same header sits above the candidate exam portal, the login screen and the legal
// pages - none of which have an account to show or a session to end.
export default function BrandHeader({ roleCode, children }) {
  return (
    <header className="brand-header">
      <div className="brand-left">
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
