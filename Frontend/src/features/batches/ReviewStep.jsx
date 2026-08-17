import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import CandidateHistoryModal from '../candidates/CandidateHistoryModal';
import CandidateValidationRow from './CandidateValidationRow';
import { extractErrorMessage } from '../../utils/passwordSchema';

// Mandatory validation step between upload and invite. Every row is checked - name, email
// format, Aadhaar format, college, optional mobile, and addresses repeated inside the batch -
// and each problem is listed against the field that caused it. Rows are corrected here rather
// than by fixing the spreadsheet and uploading it again.
//
// Saving an edit re-validates the WHOLE batch server-side, because one correction changes
// other rows' verdicts: fixing a mistyped address can turn a later row into a duplicate of it,
// and clearing a duplicate has to clear its twin. The server returns the full table and the
// counts, so nothing here recomputes them locally and drifts.
export default function ReviewStep({ batch, onFinalized }) {
  const [candidates, setCandidates] = useState([]);
  const [summary, setSummary] = useState({ total: 0, valid: 0, invalid: 0 });
  const [selected, setSelected] = useState(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [historyCandidate, setHistoryCandidate] = useState(null);

  const editable = batch.status === 'draft';

  function applyPayload(payload) {
    setCandidates(payload.rows);
    setSummary(payload.summary);
    // A row that has just become invalid must not stay checked - the selection IS the invite
    // list, and finalizing with an invalid row selected is rejected server-side anyway.
    const invalidIds = new Set(
      payload.rows.filter((r) => r.validation_status !== 'ok').map((r) => r.candidate_id),
    );
    setSelected((prev) => new Set([...prev].filter((id) => !invalidIds.has(id))));
  }

  async function refresh() {
    setLoading(true);
    try {
      applyPayload(await batchApi.getStagingCandidates(batch.batch_id));
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

  async function handleRowSave(candidateId, payload) {
    setSaving(true);
    try {
      const result = await batchApi.updateStagingCandidate(batch.batch_id, candidateId, payload);
      applyPayload(result);
      const row = result.rows.find((r) => r.candidate_id === candidateId);
      if (row && row.validation_status === 'ok') {
        toast.success('Row updated — validation passed.');
      } else if (row) {
        toast.error(row.errors?.[0] || 'Row still has validation errors.');
      }
      return true;
    } catch (err) {
      toast.error(extractErrorMessage(err));
      return false;
    } finally {
      setSaving(false);
    }
  }

  function toggleSelected(id) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  // Selects only the rows that can actually be invited - checking an invalid row just to have
  // the finalize call reject it isn't a useful thing for "Select All" to do.
  function toggleSelectAll() {
    const selectable = candidates.filter((c) => c.validation_status === 'ok');
    setSelected((prev) =>
      prev.size === selectable.length ? new Set() : new Set(selectable.map((c) => c.candidate_id)));
  }

  // Moves to "Send Invite - Confirmation" WITHOUT committing anything. The batch is only
  // finalized when the TA confirms on that screen, so "Back / Edit" comes back to a Draft that
  // is still fully editable. Finalizing here would lock the configuration behind the user's
  // back the moment they stepped forward.
  function handleFinalizeClick() {
    const selectedIds = Array.from(selected);
    if (selectedIds.length === 0) {
      toast.error('Check the candidates you want to invite first.');
      return;
    }
    const invalid = candidates.filter(
      (c) => selected.has(c.candidate_id) && c.validation_status !== 'ok'
    );
    if (invalid.length) {
      toast.error(`${invalid.length} selected row(s) have validation errors — fix or uncheck them first.`);
      return;
    }

    onFinalized({
      batch_id: batch.batch_id,
      batch_name: batch.batch_name,
      college_name: batch.college_name,
      link_valid_from: batch.link_valid_from,
      link_valid_until: batch.link_valid_until,
      exam_duration_minutes: batch.exam_duration_minutes,
      total_questions: batch.logical_questions + batch.quantitative_questions
        + batch.verbal_questions + batch.programming_questions,
      logical_cutoff: batch.logical_cutoff,
      quantitative_cutoff: batch.quantitative_cutoff,
      verbal_cutoff: batch.verbal_cutoff,
      programming_cutoff: batch.programming_cutoff,
      selected_candidate_ids: selectedIds,
      selected_count: selectedIds.length,
      skipped_count: candidates.length - selectedIds.length,
      needs_finalize: batch.status === 'draft',
    });
  }

  async function handleDownloadReport() {
    try {
      await batchApi.downloadValidationReport(batch.batch_id);
    } catch (err) {
      toast.error(extractErrorMessage(err));
    }
  }

  const duplicateCount = candidates.filter((c) => c.duplicate_status === 'duplicate_within_window').length;
  const previouslyInvitedCount = candidates.filter((c) => c.duplicate_status === 'previously_invited').length;
  const selectableCount = candidates.filter((c) => c.validation_status === 'ok').length;

  return (
    <div className="card">
      <div className="box-label">Candidate Validation</div>

      {/* This step only ever runs against a Draft batch (a finalized one has moved past
          upload/review entirely), so the Draft notice is unconditional here rather than
          gated on batch.status. */}
      <div className="alert" style={{ marginBottom: 12 }}>
        This batch is currently in <b>Draft</b> status. Candidates can be validated, but
        invitations cannot be sent until the batch is activated.
      </div>

      <div className="grid-3" style={{ marginBottom: 14 }}>
        <div className="stat-card">
          <div className="stat-num">{summary.total}</div>
          <div className="stat-lbl">Total Records</div>
        </div>
        <div className="stat-card">
          <div className="stat-num" style={{ color: 'var(--green)' }}>{summary.valid}</div>
          <div className="stat-lbl">Valid</div>
        </div>
        <div className="stat-card">
          <div className="stat-num" style={{ color: summary.invalid ? 'var(--red)' : undefined }}>
            {summary.invalid}
          </div>
          <div className="stat-lbl">Invalid</div>
        </div>
      </div>

      {summary.invalid > 0 && (
        <div className="alert error" style={{ marginBottom: 12 }}>
          {summary.invalid} row(s) failed validation and cannot be invited. Use <b>Edit</b> on a
          row to correct it — it is re-checked as soon as you save. Only valid rows are ever
          written to the batch.
          <button className="link-text" style={{ marginLeft: 10 }} onClick={handleDownloadReport}>
            ⬇ Download error report
          </button>
        </div>
      )}

      <div className="btn-row" style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 12 }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5 }}>
          <input
            type="checkbox"
            checked={selected.size === selectableCount && selectableCount > 0}
            onChange={toggleSelectAll}
            disabled={selectableCount === 0}
          />
          <b>Select All Valid</b>
        </label>
        <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>
          {selected.size} of {selectableCount} valid row(s) selected to invite
        </span>
      </div>
      <div className="annot">
        Check the candidates who should receive the assessment invite. Use each row&apos;s Status
        and History to spot a prior attempt — leave those rows unchecked and they stay on the
        batch without being emailed.
      </div>

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th></th>
              <th>Row</th>
              <th>Name</th>
              <th>Email</th>
              <th>Mobile</th>
              <th>Aadhaar</th>
              <th>Validation</th>
              <th>Errors</th>
              <th>Status</th>
              <th>Last Attempt</th>
              <th>History</th>
              <th>Edit</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={12}>Loading…</td></tr>
            ) : candidates.length === 0 ? (
              <tr><td colSpan={12}>No candidates uploaded yet.</td></tr>
            ) : (
              candidates.map((c) => (
                <CandidateValidationRow
                  key={c.candidate_id}
                  row={c}
                  selected={selected.has(c.candidate_id)}
                  onToggleSelected={toggleSelected}
                  onSave={handleRowSave}
                  onViewHistory={setHistoryCandidate}
                  saving={saving}
                  editable={editable}
                />
              ))
            )}
          </tbody>
        </table>
      </div>

      {previouslyInvitedCount > 0 && (
        <div className="alert" style={{ marginTop: 14 }}>
          {previouslyInvitedCount} row(s) appear in an earlier batch but never sat the
          assessment — no cooling-off period applies. Safe to invite.
        </div>
      )}

      {duplicateCount > 0 && (
        <div className="alert error" style={{ marginTop: 14 }}>
          {duplicateCount} row(s) sat the assessment inside the cooling-off window. Leave them
          unchecked to skip them, or check them to invite anyway — it&apos;s your call.
        </div>
      )}

      <div className="btn-row" style={{ marginTop: 16 }}>
        <button className="btn primary" style={{ width: 'auto' }} onClick={handleFinalizeClick}
                disabled={saving || candidates.length === 0}>
          Create Batch &amp; Proceed to Send Invite
        </button>
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
