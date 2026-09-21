import { Link } from 'react-router-dom';
import toast from 'react-hot-toast';
import { SkeletonTableRows } from '../../components/loading/Skeleton';
import { formatDateDMY } from '../../utils/datetime';

const STATUS_PILL = {
  pending_invite: 'gray', invited: 'blue', in_progress: 'blue',
  completed: 'green', terminated: 'amber', no_show: 'gray',
};
// Borderline is amber, matching ReviewStep's DUPLICATE_PILL convention - green safe, amber
// worth a look, red needs a decision. Amber rather than red because a borderline candidate has
// not failed; nobody has ruled either way yet.
const RESULT_PILL = { pending: 'gray', pass: 'green', fail: 'red', borderline: 'amber' };
// Email delivery, shown separately from the candidate's pipeline Status on purpose: Status
// flips to "Invited" when the invitation row is created, which happens BEFORE the send is
// attempted. So Status alone reads as success even when the email never left.
const EMAIL_PILL = {
  sent: 'green', queued: 'blue', failed: 'red',
};

// Select-all/notify/export toolbar + the results table together, since every screen that lists
// candidates (All Candidates, Batch Details) needs both and they share selection state.
export default function CandidateTable({
  candidates, loading, selected, onToggleRow, onToggleSelectAll, onEdit, onOpenNotify, onOpenExport,
  onOpenCertification, onOpenInvite, sections = [],
}) {
  // 19 fixed columns plus one per section - the count is no longer a constant, and the skeleton
  // and empty-state row have to match the header or the table renders visibly ragged.
  const columnCount = 19 + sections.length;
  // Only checked rows are emailed, so an empty selection is a mistake worth naming rather
  // than a silently dead button.
  function requireSelection(action) {
    return () => {
      if (selected.size === 0) {
        toast.error('Select at least one candidate first — only checked rows are emailed.');
        return;
      }
      action();
    };
  }

  return (
    <>
      <div className="btn-row" style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 12 }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5 }}>
          <input type="checkbox" checked={selected.size === candidates.length && candidates.length > 0} onChange={onToggleSelectAll} />
          <b>Select All</b>
        </label>
        {/* Passed by both Batch Details and All Candidates. Sends a genuinely NEW token, so it
            also covers candidates whose original link expired. Still prop-gated rather than
            always-on, so a future caller can render this table without the email actions. */}
        {onOpenInvite && (
          <button className="btn" onClick={requireSelection(onOpenInvite)}>
            📧 Send New Invite Link ({selected.size})
          </button>
        )}
        <button className="btn" onClick={requireSelection(onOpenNotify)}>
          ✉ Send Notification Email ({selected.size})
        </button>
        {/* Passed by both Batch Details and All Candidates - a shortlist worth certifying is
            often assembled across batches, not just within one. */}
        {onOpenCertification && (
          <button className="btn" onClick={requireSelection(onOpenCertification)}>
            🎓 Send Certification Link ({selected.size})
          </button>
        )}
        <button className="btn" style={{ marginLeft: 'auto' }} onClick={onOpenExport}>
          ⬇ Export Candidates (Excel)
        </button>
      </div>

      <div className="table-scroll" aria-busy={loading}>
        <table className="data-table">
          <thead>
            <tr>
              <th></th><th>Name</th><th>Email</th><th>Mobile</th><th>Batch Name</th><th>College</th><th>Degree</th>
              <th>Stream</th><th>Percentage</th><th>Passing Out Year</th><th>Location</th><th>Aadhaar Last 4</th>
              <th>Date of Birth</th>
              <th>Status</th><th>Email Status</th>
              {/* One column per section that EXISTS, not per section this page's candidates
                  happen to use: All Candidates lists people from different batches side by side,
                  and those batches can run different sections. A candidate whose own batch never
                  included a section shows a dash for it, which is the honest reading. */}
              {sections.map((s) => <th key={s.section_key}>{s.section_name}</th>)}
              <th>Overall</th><th>Result</th><th>History</th><th>Edit</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <SkeletonTableRows rows={6} columns={columnCount} />
            ) : candidates.length === 0 ? (
              <tr><td colSpan={columnCount}>No candidates found.</td></tr>
            ) : (
              candidates.map((c) => (
                <tr key={c.candidate_id}>
                  <td><input type="checkbox" checked={selected.has(c.candidate_id)} onChange={() => onToggleRow(c.candidate_id)} /></td>
                  <td>{c.full_name}</td>
                  <td>{c.email}</td>
                  <td>{c.phone || '—'}</td>
                  <td>{c.batch_name}</td>
                  <td>{c.college_name || '—'}</td>
                  <td>{c.degree || '—'}</td>
                  <td>{c.stream || '—'}</td>
                  <td>{c.percentage != null ? `${c.percentage}%` : '—'}</td>
                  <td>{c.passing_out_year || '—'}</td>
                  <td>{c.location || '—'}</td>
                  <td>{c.aadhaar_last4 || '—'}</td>
                  <td>{formatDateDMY(c.date_of_birth)}</td>
                  <td><span className={`pill ${STATUS_PILL[c.status] || 'gray'}`}>{c.status_display}</span></td>
                  {/* The failure reason is the title text rather than a visible cell: it is a
                      long API message, and only matters for the rows that failed. */}
                  <td title={c.email_error || undefined}>
                    <span className={`pill ${EMAIL_PILL[c.email_status] || 'gray'}`}>
                      {c.email_status_display || 'Not invited'}
                    </span>
                    {c.email_status === 'failed' && c.email_error && (
                      <div style={{ fontSize: 10.5, color: 'var(--brand-red)', marginTop: 3,
                                   maxWidth: 200, whiteSpace: 'normal' }}>
                        {c.email_error}
                      </div>
                    )}
                  </td>
                  {sections.map((s) => (
                    <td key={s.section_key}>{c.section_scores?.[s.section_key] ?? '—'}</td>
                  ))}
                  {/* Marks, matching the per-section columns beside it. total_correct is a
                      question COUNT and overall_score a PERCENTAGE - either one here would put
                      a different unit next to those columns. */}
                  <td>
                    {c.total_marks_earned != null
                      ? `${c.total_marks_earned}/${c.overall_total}` : '—'}
                  </td>
                  <td><span className={`pill ${RESULT_PILL[c.result] || 'gray'}`}>{c.result_display}</span></td>
                  <td><Link className="link-text" to={`/candidates/${c.candidate_id}`}>View History</Link></td>
                  <td><button className="btn small" onClick={() => onEdit(c)}>Edit</button></td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
