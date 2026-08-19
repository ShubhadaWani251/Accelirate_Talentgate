// Rendered in-place by ExamAttemptPage on a manual/time-expiry submit - not a separate route,
// since the wireframe treats this as a terminal state of the exam screen, not somewhere a
// candidate navigates back to.
//
// Deliberately shows ONLY section name + score - no overall PASS/FAIL banner, no cutoff column,
// no Cleared/Not Cleared pill. Per product decision, the candidate sees their marks only; pass/
// fail and cutoff comparisons are the Staffing User's call, made from the admin candidate view.
export default function ExamResult({ result }) {
  return (
    <div className="auth-shell">
      <div className="auth-card" style={{ maxWidth: 360 }}>
        <h3 style={{ textAlign: 'center' }}>Assessment Submitted</h3>
        <div className="card" style={{ marginTop: 8 }}>
          <div className="box-label">Section-wise Marks</div>
          <table style={{ width: '100%', fontSize: 12.5, borderCollapse: 'collapse' }}>
            <thead>
              <tr style={{ color: 'var(--muted)', textAlign: 'left' }}>
                <th style={{ paddingBottom: 6 }}>Section</th>
                <th style={{ paddingBottom: 6 }}>Score</th>
              </tr>
            </thead>
            <tbody>
              {result.sections.map((s) => (
                <tr key={s.key} style={{ borderTop: '1px solid var(--line-soft)' }}>
                  <td style={{ padding: '7px 0' }}>{s.label}</td>
                  <td style={{ padding: '7px 0' }}>{s.score}/{s.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 12 }}>
            The Staffing User will contact you regarding next steps.
          </div>
        </div>

        {/* No "Exit Window" button here on purpose: window.close() only works on a tab that
            JavaScript itself opened via window.open(), which is never the case for a candidate
            arriving through an emailed assessment link. The button was silently inert in exactly
            the real-world path that matters, so a plain instruction is more honest than a control
            that appears broken. Exiting full-screen from this terminal screen is also fine - the
            attempt is already finalized, so nothing here can trigger a termination. */}
        <div style={{ fontSize: 12, color: 'var(--muted)', textAlign: 'center', marginTop: 16 }}>
          Your assessment is complete — you can now close this browser tab.
        </div>
      </div>
    </div>
  );
}
