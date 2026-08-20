import { useState } from 'react';
import toast from 'react-hot-toast';
import * as userApi from '../../api/userApi';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';

// Deactivation, not deletion: the account row and all its history are preserved, the user
// simply can't sign in. They stay listed in User Management as Inactive and can be switched
// back to Active from Edit User.
export default function DeactivateUserModal({ user, onClose, onDeactivated }) {
  const [working, setWorking] = useState(false);

  async function handleDeactivate() {
    setWorking(true);
    try {
      const res = await userApi.deactivateUser(user.user_id);
      toast.success(res.detail);
      onDeactivated();
    } catch (err) {
      toast.error(extractErrorMessage(err));
      setWorking(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <h4>Deactivate User?</h4>
        <p>
          Are you sure you want to deactivate <b>{user.full_name}</b>? The user will no longer
          be able to access TalentGate.
        </p>
        <p style={{ marginTop: -8 }}>
          Their account and history are kept — you can reactivate them later from Edit User.
        </p>
        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn danger" onClick={handleDeactivate} disabled={working}>
            <ButtonSpinner loading={working}>Deactivate User</ButtonSpinner>
          </button>
        </div>
      </div>
    </div>
  );
}
