import { useRef, useState } from 'react';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';

// Draft-only, unlike DeactivateBatchModal - a Draft has no invites or results yet, so there is
// nothing this loses. Anything past Draft is deactivated instead (see that modal).
export default function DeleteDraftBatchModal({ batch, onClose, onDeleted }) {
  const [busy, setBusy] = useState(false);
  // Ref, not state: two fast clicks would both read the same stale `busy` before React
  // flushes the update, firing the delete call twice.
  const busyRef = useRef(false);

  async function handleDelete() {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    try {
      const res = await batchApi.deleteBatch(batch.batch_id);
      toast.success(res.detail);
      onDeleted(batch.batch_id);
    } catch (err) {
      toast.error(extractErrorMessage(err));
      busyRef.current = false;
      setBusy(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <h4>Delete this draft?</h4>
        <p>
          <b>{batch.batch_name}</b> and its {batch.total_candidates} uploaded candidate(s) will
          be permanently deleted. This cannot be undone.
        </p>
        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn danger" onClick={handleDelete} disabled={busy}>
            <ButtonSpinner loading={busy}>Delete Draft</ButtonSpinner>
          </button>
        </div>
      </div>
    </div>
  );
}
