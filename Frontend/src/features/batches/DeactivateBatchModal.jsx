import { useRef, useState } from 'react';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { extractErrorMessage } from '../../utils/passwordSchema';

export default function DeactivateBatchModal({ batch, onClose, onDeactivated }) {
  const [busy, setBusy] = useState(false);
  // Ref, not state: two fast clicks would both read the same stale `busy` before React
  // flushes the update, firing the deactivate call twice.
  const busyRef = useRef(false);

  async function handleDeactivate() {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    try {
      const res = await batchApi.deactivateBatch(batch.batch_id);
      toast.success(res.detail);
      onDeactivated(res);
    } catch (err) {
      toast.error(extractErrorMessage(err));
      busyRef.current = false;
      setBusy(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <h4>Deactivate this batch?</h4>
        <p>
          <b>{batch.batch_name}</b> will be marked Cancelled and stop accepting new invites. Its
          candidates, scores and results all stay exactly as they are — nothing is deleted.
        </p>
        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn danger" onClick={handleDeactivate} disabled={busy}>
            {busy ? 'Deactivating…' : 'Deactivate Batch'}
          </button>
        </div>
      </div>
    </div>
  );
}
