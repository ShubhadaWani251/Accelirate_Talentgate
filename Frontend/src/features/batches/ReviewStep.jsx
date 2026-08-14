import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import CandidateHistoryModal from '../candidates/CandidateHistoryModal';
import { formatDateTime } from '../../utils/datetime';
import { extractErrorMessage } from '../../utils/passwordSchema';

const VALIDATION_PILL = { ok: 'green' };
const DUPLICATE_PILL = {
  new: 'gray',
  duplicate_cleared: 'amber',
  duplicate_within_window: 'red',
};

function Pill({ text, color }) {
  return <span className={`pill ${color}`}>{text}</span>;
}

export default function ReviewStep({ batch, onFinalized }) {
  const [candidates, setCandidates] = useState([]);
  const [selected, setSelected] = useState(new Set());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [historyCandidate, setHistoryCandidate] = useState(null);

  async function refresh() {
    setLoading(true);
    try {
      setCandidates(await batchApi.getStagingCandidates(batch.batch_id));
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

  function toggleSelected(id) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    setSelected((prev) => (prev.size === candidates.length ? new Set() : new Set(candidates.map((c) => c.candidate_id))));
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
      toast.error(`${invalid.length} selected row(s) have validation errors — uncheck them first.`);
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

  const okCount = candidates.filter((c) => c.validation_status === 'ok').length;
  const duplicateCount = candidates.filter((c) => c.duplicate_status === 'duplicate_within_window').length;

  return (
    <div className="card">
      <div className="box-label">Upload Review — {candidates.length} row(s), {okCount} OK</div>

      <div className="btn-row" style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 12 }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5 }}>
          <input
            type="checkbox"
            checked={selected.size === candidates.length && candidates.length > 0}
            onChange={toggleSelectAll}
          />
          <b>Select All</b>
        </label>
        <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>
          {selected.size} of {candidates.length} selected to invite
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
              <th>Aadhaar</th>
              <th>Validation</th>
              <th>Status</th>
              <th>Last Attempt</th>
              <th>History</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={9}>Loading…</td></tr>
            ) : candidates.length === 0 ? (
              <tr><td colSpan={9}>No candidates uploaded yet.</td></tr>
            ) : (
              candidates.map((c) => (
                <tr key={c.candidate_id}>
                  <td><input type="checkbox" checked={selected.has(c.candidate_id)} onChange={() => toggleSelected(c.candidate_id)} /></td>
                  <td>{c.upload_row_number ?? '—'}</td>
                  <td>{c.full_name || '(missing)'}</td>
                  <td>{c.email || '(missing)'}</td>
                  <td>{c.aadhaar_masked || '(missing)'}</td>
                  <td><Pill text={c.validation_status_display} color={VALIDATION_PILL[c.validation_status] || 'red'} /></td>
                  <td><Pill text={c.duplicate_status_display} color={DUPLICATE_PILL[c.duplicate_status] || 'gray'} /></td>
                  <td>{c.last_attempt ? `${c.last_attempt.batch_name} · ${formatDateTime(c.last_attempt.date)}` : '—'}</td>
                  <td>
                    <button className="btn small" onClick={() => setHistoryCandidate(c)}>View History</button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {duplicateCount > 0 && (
        <div className="alert" style={{ marginTop: 14 }}>
          {duplicateCount} row(s) sat the assessment inside the cooling-off window. Leave them
          unchecked to skip them, or check them to invite anyway — it&apos;s your call.
        </div>
      )}

      <div className="btn-row" style={{ marginTop: 16 }}>
        <button className="btn primary" style={{ width: 'auto' }} onClick={handleFinalizeClick} disabled={busy || candidates.length === 0}>
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
