import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import CandidateHistoryModal from '../candidates/CandidateHistoryModal';
import CandidateErrorRow from './CandidateErrorRow';
import { SkeletonTableRows } from '../../components/loading/Skeleton';
import { extractErrorMessage } from '../../utils/passwordSchema';

// Step 3 of the upload: the error queue. Only rows that FAILED validation appear here, and the
// step is done when the table is empty - either because every row was corrected or because the
// unwanted ones were deleted.
//
// That's what lets the next step drop its Validation column entirely: nothing invalid can reach
// it, so there is no verdict left to show.
//
// Every column of the upload template is shown and editable, because a row can be wrong in a
// field the summary table wouldn't otherwise display (a percentage that isn't a number, a
// college of "12345"), and the reviewer can't fix what they can't see.
export default function FixErrorsStep({ batch, onDone }) {
  const [rows, setRows] = useState([]);
  const [summary, setSummary] = useState({ total: 0, valid: 0, invalid: 0 });
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [historyCandidate, setHistoryCandidate] = useState(null);

  function apply(payload) {
    setRows(payload.rows);
    setSummary(payload.summary);
  }

  async function refresh() {
    setLoading(true);
    try {
      apply(await batchApi.getStagingCandidates(batch.batch_id));
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batch.batch_id]);

  const invalidRows = rows.filter((r) => r.validation_status !== 'ok');
  const clean = !loading && invalidRows.length === 0;

  async function handleRowSave(candidateId, payload) {
    setSaving(true);
    try {
      const result = await batchApi.updateStagingCandidate(batch.batch_id, candidateId, payload);
      apply(result);
      const row = result.rows.find((r) => r.candidate_id === candidateId);
      if (row?.validation_status === 'ok') toast.success('Row corrected — now valid.');
      else if (row) toast.error(row.errors?.[0] || 'Row still has errors.');
      return true;
    } catch (err) {
      toast.error(extractErrorMessage(err));
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(row) {
    setSaving(true);
    try {
      apply(await batchApi.deleteCandidates(batch.batch_id, [row.candidate_id]));
      toast.success('Row removed from this batch.');
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteAllInvalid() {
    const ids = invalidRows.map((r) => r.candidate_id);
    setSaving(true);
    try {
      apply(await batchApi.deleteCandidates(batch.batch_id, ids));
      toast.success(`${ids.length} row(s) removed from this batch.`);
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="card">
      <div className="box-label">Candidate Validation — Rows Needing Attention</div>

      <div className="grid-3" style={{ marginBottom: 14 }}>
        <div className="stat-card">
          <div className="stat-num">{summary.total}</div>
          <div className="stat-lbl">Total Uploaded</div>
        </div>
        <div className="stat-card">
          <div className="stat-num" style={{ color: 'var(--green)' }}>{summary.valid}</div>
          <div className="stat-lbl">Valid</div>
        </div>
        <div className="stat-card">
          <div className="stat-num" style={{ color: summary.invalid ? 'var(--red)' : undefined }}>
            {summary.invalid}
          </div>
          <div className="stat-lbl">Needs Fixing</div>
        </div>
      </div>

      {clean ? (
        <div className="alert success">
          {summary.total === 0
            ? 'No candidates left on this batch. Go back and upload a file.'
            : `All ${summary.total} row(s) passed validation — nothing to fix here.`}
        </div>
      ) : (
        <>
          <div className="alert error" style={{ marginBottom: 12 }}>
            Only rows that failed validation are listed. <b>Edit</b> a row to correct it — it is
            re-checked the moment you save — or <b>Delete</b> it to drop it from this batch.
            You can continue once this list is empty.
            <button className="link-text" style={{ marginLeft: 10 }}
                    onClick={() => batchApi.downloadValidationReport(batch.batch_id)
                      .catch((err) => toast.error(extractErrorMessage(err)))}>
              ⬇ Download error report
            </button>
          </div>

          <div className="btn-row" style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
            <button className="btn danger" onClick={handleDeleteAllInvalid} disabled={saving}>
              🗑 Delete all {invalidRows.length} invalid row(s)
            </button>
          </div>
        </>
      )}

      {!clean && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Row</th>
                <th>Name</th>
                <th>Email</th>
                <th>Mobile</th>
                <th>Aadhaar Last 4</th>
                <th>College Name</th>
                <th>Degree</th>
                <th>Stream</th>
                <th>Percentage</th>
                <th>Passing Out Year</th>
                <th>Location</th>
                <th>Errors</th>
                <th>Duplicate</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading ? (
                <SkeletonTableRows rows={5} columns={14} />
              ) : (
                invalidRows.map((r) => (
                  <CandidateErrorRow
                    key={r.candidate_id}
                    row={r}
                    onSave={handleRowSave}
                    onDelete={handleDelete}
                    onViewHistory={setHistoryCandidate}
                    saving={saving}
                  />
                ))
              )}
            </tbody>
          </table>
        </div>
      )}

      <div className="btn-row" style={{ marginTop: 16 }}>
        <button className="btn primary" onClick={onDone}
                disabled={!clean || summary.total === 0}>
          Continue to Upload Review →
        </button>
        {!clean && (
          <span style={{ fontSize: 12.5, color: 'var(--muted)', marginLeft: 10 }}>
            Fix or delete the {invalidRows.length} row(s) above to continue.
          </span>
        )}
      </div>

      {historyCandidate && (
        <CandidateHistoryModal
          candidate={historyCandidate}
          onClose={() => setHistoryCandidate(null)}
        />
      )}
    </div>
  );
}
