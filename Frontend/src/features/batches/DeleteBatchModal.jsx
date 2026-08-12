import { useState } from 'react';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { extractErrorMessage } from '../../utils/passwordSchema';

export default function DeleteBatchModal({ batch, onClose, onDeleted }) {
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    setDeleting(true);
    try {
      const res = await batchApi.deleteBatch(batch.batch_id);
      toast.success(res.detail);
      onDeleted(res);
    } catch (err) {
      toast.error(extractErrorMessage(err));
      setDeleting(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <h4>Delete Batch?</h4>
        <p>
          If <b>{batch.batch_name}</b> has no invites sent yet, it's removed outright. If
          invites have already gone out, it's deactivated (marked Cancelled) instead, so
          candidate history and results stay intact.
        </p>
        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn danger" onClick={handleDelete} disabled={deleting}>
            {deleting ? 'Removing…' : 'Delete / Deactivate Batch'}
          </button>
        </div>
      </div>
    </div>
  );
}
