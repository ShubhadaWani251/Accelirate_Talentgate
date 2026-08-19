const ROLE_LABELS = {
  admin: 'Administrator Portal',
  ta: 'Staffing User Portal',
  candidate: 'Candidate Exam Portal',
};

export default function BrandHeader({ roleCode }) {
  return (
    <header className="brand-header">
      <div className="brand-left">
        <div className="brand-name">
          Accelirate TalentGate
          <div className="brand-tagline">Candidate Evaluation Platform</div>
        </div>
      </div>
      {roleCode && <span className="brand-role-badge">{ROLE_LABELS[roleCode] || roleCode}</span>}
    </header>
  );
}
