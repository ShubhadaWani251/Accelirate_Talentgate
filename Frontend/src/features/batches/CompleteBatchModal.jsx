import { useRef, useState } from 'react';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';

export default function CompleteBatchModal({ batch, onClose, onCompleted }) {
  const [busy, setBusy] = useState(false);
  // Ref, not state: two fast clicks would both read the same stale `busy` before React
  // flushes the update, firing the complete call twice.
  const busyRef = useRef(false);

  async function handleComplete() {
    if (busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    try {
      const res = await batchApi.completeBatch(batch.batch_id);
      toast.success(res.detail);
      onCompleted(res);
    } catch (err) {
      toast.error(extractErrorMessage(err));
      busyRef.current = false;
      setBusy(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <h4>Mark this batch completed?</h4>
        <p>
          <b>{batch.batch_name}</b> will be marked Completed. This is a manual call — nothing in
          the app tracks this on its own, so mark it only once you consider the drive actually
          done. Its candidates, scores and results all stay exactly as they are, and invites can
          still be sent afterward if needed.
        </p>
        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
          <button className="btn primary" onClick={handleComplete} disabled={busy}>
            <ButtonSpinner loading={busy}>Mark Completed</ButtonSpinner>
          </button>
        </div>
      </div>
    </div>
  );
}
