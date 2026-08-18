import { Link } from 'react-router-dom';
import toast from 'react-hot-toast';

const STATUS_PILL = {
  pending_invite: 'gray', invited: 'blue', in_progress: 'blue',
  completed: 'green', terminated: 'amber', no_show: 'gray',
};
const RESULT_PILL = { pending: 'gray', pass: 'green', fail: 'red' };

// Select-all/notify/export toolbar + the results table together, since every screen that lists
// candidates (All Candidates, Batch Details) needs both and they share selection state.
export default function CandidateTable({
  candidates, loading, selected, onToggleRow, onToggleSelectAll, onEdit, onOpenNotify, onOpenExport,
  onOpenCertification, onOpenInvite,
}) {
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
        {/* Batch Details passes this; invites are only ever sent to checked rows, so anyone
            skipped during upload review is re-invited by choosing them explicitly here. */}
        {onOpenInvite && (
          <button className="btn" onClick={requireSelection(onOpenInvite)}>
            📧 Send Invite Link ({selected.size})
          </button>
        )}
        <button className="btn" onClick={requireSelection(onOpenNotify)}>
          ✉ Send Notification Email ({selected.size})
        </button>
        {/* Batch Details passes this; All Candidates deliberately doesn't - certification is
            sent per-batch once its results are in. */}
        {onOpenCertification && (
          <button className="btn" onClick={requireSelection(onOpenCertification)}>
            🎓 Send Certification Link ({selected.size})
          </button>
        )}
        <button className="btn" style={{ marginLeft: 'auto' }} onClick={onOpenExport}>
          ⬇ Export Candidates (Excel)
        </button>
      </div>

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th></th><th>Name</th><th>Email</th><th>Mobile</th><th>Batch Name</th><th>College</th><th>Degree</th>
              <th>Stream</th><th>Percentage</th><th>Passing Out Year</th><th>Location</th><th>Aadhaar</th>
              <th>Status</th><th>Logical</th><th>Quant.</th><th>Verbal</th><th>Programming</th>
              <th>Overall</th><th>Result</th><th>History</th><th>Edit</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={21}>Loading…</td></tr>
            ) : candidates.length === 0 ? (
              <tr><td colSpan={21}>No candidates found.</td></tr>
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
                  <td>{c.aadhaar_masked || '—'}</td>
                  <td><span className={`pill ${STATUS_PILL[c.status] || 'gray'}`}>{c.status_display}</span></td>
                  <td>{c.logical_score ?? '—'}</td>
                  <td>{c.quantitative_score ?? '—'}</td>
                  <td>{c.verbal_score ?? '—'}</td>
                  <td>{c.programming_score ?? '—'}</td>
                  <td>{c.overall_score ?? '—'}</td>
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
