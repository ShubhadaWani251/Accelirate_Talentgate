const ROLE_LABELS = {
  admin: 'Administrator',
  ta: 'Staffing User',
  candidate: 'Candidate Exam',
};

export default function BrandFooter({ roleCode }) {
  return (
    <footer className="brand-footer">
      <span>&copy; 2026 Accelirate Inc. &middot; Accelirate TalentGate {ROLE_LABELS[roleCode] ? `— ${ROLE_LABELS[roleCode]} Portal` : ''}</span>
      <div className="foot-links">
        {/* Plain <a> tags, not react-router's <Link>, and deliberately so: this footer also
            renders inside ErrorPage, which is ErrorBoundary's fallback - and ErrorBoundary sits
            OUTSIDE <BrowserRouter> in AppRouter.jsx. A <Link> rendered there would throw for
            missing Router context, which would crash the error page itself while it is trying
            to report a different, unrelated crash. A plain anchor triggers an ordinary page
            load, which works identically whether or not a Router happens to be mounted. */}
        {/* Candidates have no staff account and nothing in Help & Support applies to them (it's
            written for admins/TAs) - only shown on the staff-facing roles. */}
        {roleCode !== 'candidate' && <a className="flink" href="/help">Help &amp; Support</a>}
        <a className="flink" href="/privacy">Privacy Policy</a>
        <span>v0.1</span>
      </div>
    </footer>
  );
}
