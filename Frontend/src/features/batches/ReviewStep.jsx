import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { formatDateTime } from '../../utils/datetime';
import { extractErrorMessage } from '../../utils/passwordSchema';
import ConfirmModal from '../../components/common/ConfirmModal';

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
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      setCandidates(await batchApi.getStagingCandidates(batch.batch_id));
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

  async function confirmDeleteSelected() {
    setConfirmingDelete(false);
    setBusy(true);
    try {
      await batchApi.deleteCandidates(batch.batch_id, Array.from(selected));
      setSelected(new Set());
      await refresh();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleClearDuplicate(candidateId) {
    setBusy(true);
    try {
      await batchApi.clearDuplicate(batch.batch_id, candidateId);
      await refresh();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleFinalize() {
    setBusy(true);
    try {
      const summary = await batchApi.finalizeBatch(batch.batch_id);
      onFinalized(summary);
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  const okCount = candidates.filter((c) => c.validation_status === 'ok').length;
  const blockingCount = candidates.filter((c) => c.duplicate_status === 'duplicate_within_window').length;

  return (
    <div className="card">
      <div className="box-label">Upload Review — {candidates.length} row(s), {okCount} OK</div>

      <div className="btn-row" style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
        <button className="btn" onClick={() => setConfirmingDelete(true)} disabled={busy || selected.size === 0}>
          🗑 Delete Selected ({selected.size})
        </button>
      </div>

      {confirmingDelete && (
        <ConfirmModal
          title="Delete selected candidates?"
          message={`This removes ${selected.size} candidate(s) from this upload batch before it's finalized. This cannot be undone.`}
          confirmLabel="Delete"
          danger
          onConfirm={confirmDeleteSelected}
          onCancel={() => setConfirmingDelete(false)}
        />
      )}

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th><input type="checkbox" checked={selected.size === candidates.length && candidates.length > 0} onChange={toggleSelectAll} /></th>
              <th>Row</th>
              <th>Name</th>
              <th>Email</th>
              <th>Aadhaar</th>
              <th>Validation</th>
              <th>Duplicate Status</th>
              <th>Last Attempt</th>
              <th></th>
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
                    {c.duplicate_status === 'duplicate_within_window' && (
                      <button className="btn small" style={{ padding: '4px 10px', fontSize: 11.5 }}
                        onClick={() => handleClearDuplicate(c.candidate_id)} disabled={busy}>
                        Clear
                      </button>
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {blockingCount > 0 && (
        <div className="alert error" style={{ marginTop: 14 }}>
          {blockingCount} row(s) have an unresolved duplicate within the cooling-off window — clear or remove them before finalizing.
        </div>
      )}

      <div className="btn-row" style={{ marginTop: 16 }}>
        <button className="btn primary" style={{ width: 'auto' }} onClick={handleFinalize} disabled={busy || candidates.length === 0}>
          Create Batch & Proceed to Send Invite
        </button>
      </div>
    </div>
  );
}
