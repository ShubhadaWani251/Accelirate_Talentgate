import { useState } from 'react';
import toast from 'react-hot-toast';
import * as userApi from '../../api/userApi';
import { extractErrorMessage } from '../../utils/passwordSchema';

// Corrected copy vs. the wireframe's "permanently removes... cannot be undone" - the backend
// implements this as a soft delete (User.is_deleted), consistent with Batch.primary_ta_user
// being on_delete=PROTECT.
export default function DeleteUserModal({ user, onClose, onDeleted }) {
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    setDeleting(true);
    try {
      const res = await userApi.deleteUser(user.user_id);
      toast.success(res.detail);
      onDeleted();
    } catch (err) {
      toast.error(extractErrorMessage(err));
      setDeleting(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <h4>Delete User?</h4>
        <p>
          This deactivates <b>{user.full_name}</b>'s account and revokes their access to
          TalentGate. If they still own open batches, deletion will be blocked until those are
          reassigned or finalized.
        </p>
        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn danger" onClick={handleDelete} disabled={deleting}>
            {deleting ? 'Deleting…' : 'Delete User'}
          </button>
        </div>
      </div>
    </div>
  );
}
