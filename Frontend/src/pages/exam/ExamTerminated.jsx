const FALLBACK_MESSAGE =
  'Your assessment was ended automatically because a proctoring rule was triggered.';

// Reached automatically when a zero-tolerance proctoring trigger fires - not a normal navigation
// target, and rendered in-place by ExamAttemptPage rather than as its own route. `message` is the
// specific, cause-tied text from the backend (see services/exam_session.TERMINATION_MESSAGES) -
// never one generic message regardless of what actually happened.
export default function ExamTerminated({ message }) {
  return (
    <div className="auth-shell">
      <div className="auth-card" style={{ maxWidth: 400, borderTopColor: 'var(--brand-red)', textAlign: 'center' }}>
        <div style={{ fontSize: 32, color: 'var(--brand-red-dark)', marginBottom: 6 }}>&#10005;</div>
        <div style={{ fontSize: 12, color: 'var(--muted)' }}>Your Result</div>
        <div style={{ fontSize: 24, fontWeight: 800, color: 'var(--brand-red-dark)', margin: '8px 0' }}>
          TERMINATED
        </div>
        <div style={{ fontSize: 12.5, lineHeight: 1.6 }}>
          {message || FALLBACK_MESSAGE}
        </div>
        <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 14 }}>
          This attempt has been logged and reported to the Staffing User. Contact them if you
          believe this was in error.
        </div>
      </div>
    </div>
  );
}
