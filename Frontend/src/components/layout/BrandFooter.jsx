const ROLE_LABELS = {
  admin: 'Administrator',
  ta: 'Staffing User',
};

export default function BrandFooter({ roleCode }) {
  return (
    <footer className="brand-footer">
      <span>&copy; 2026 Accelirate Inc. &middot; Accelirate TalentGate {ROLE_LABELS[roleCode] ? `— ${ROLE_LABELS[roleCode]} Portal` : ''}</span>
      <div className="foot-links">
        <span className="flink">Help &amp; Support</span>
        <span className="flink">Privacy Policy</span>
        <span>v0.1</span>
      </div>
    </footer>
  );
}
