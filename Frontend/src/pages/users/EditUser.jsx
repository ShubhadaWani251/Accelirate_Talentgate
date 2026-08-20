import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import * as userApi from '../../api/userApi';
import DeactivateUserModal from '../../features/users/DeactivateUserModal';
import ToggleSwitch from '../../components/common/ToggleSwitch';
import ServerErrorPage from '../../components/error/ServerErrorPage';
import NotFoundPage from '../../components/error/NotFoundPage';
import { isResourceMissing } from '../../utils/apiError';
import { Skeleton, SkeletonForm, SkeletonPage } from '../../components/loading/Skeleton';
import { selectUser } from '../../features/auth/authSlice';
import { useSelector } from 'react-redux';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';

const BATCH_STATUS_PILL = { draft: 'gray', in_progress: 'blue', completed: 'green', cancelled: 'red' };

export default function EditUser() {
  const { id } = useParams();
  const navigate = useNavigate();
  const currentUser = useSelector(selectUser);
  const [user, setUser] = useState(null);
  const [form, setForm] = useState(null);
  const [loading, setLoading] = useState(true);
  // null | 'notfound' | 'server' - which error page (if any) replaces this page.
  const [loadError, setLoadError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [deactivateOpen, setDeactivateOpen] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      const data = await userApi.getUser(id);
      setUser(data);
      setForm({ first_name: data.first_name, last_name: data.last_name, role: data.role_code, is_active: data.is_active });
      setLoadError(null);
    } catch (err) {
      toast.error(extractErrorMessage(err));
      // Otherwise user/form stay null and the page shows "Loading…" permanently.
      setLoadError(isResourceMissing(err) ? 'notfound' : 'server');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  if (loadError === 'notfound') return <NotFoundPage standalone={false} />;
  if (loadError) return <ServerErrorPage onRetry={refresh} />;

  if (loading || !user || !form) {
    return (
      <SkeletonPage label="Loading user…">
        <div className="card" style={{ maxWidth: 520 }}>
          <Skeleton width="34%" height={11} style={{ marginBottom: 14 }} />
          <SkeletonForm fields={4} />
          <Skeleton width={130} height={38} radius={999} style={{ marginTop: 8 }} />
        </div>
      </SkeletonPage>
    );
  }

  const isSelf = currentUser?.user_id === user.user_id;

  async function handleSave() {
    setSaving(true);
    try {
      await userApi.updateUser(id, form);
      toast.success('Changes saved.');
      navigate('/admin/users');
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="page-wide">
      <h3>Edit User Access — {user.full_name}</h3>

      <div className="card">
        <div className="box-label">User Details</div>
        <div className="grid-2">
          <div className="field">
            <label>Name</label>
            <input value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} />
          </div>
          <div className="field">
            <label>Corporate Email</label>
            <input value={user.email} disabled />
          </div>
        </div>
        <div className="grid-2">
          <div className="field">
            <label>Last Name</label>
            <input value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} />
          </div>
          <div className="field">
            <label>Role</label>
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              <option value="ta">Staffing User</option>
              <option value="admin">Administrator</option>
            </select>
          </div>
        </div>
        <div className="field">
          <label>Account Status</label>
          {isSelf ? (
            <p style={{ fontSize: 12, color: 'var(--muted)' }}>You can't deactivate your own account.</p>
          ) : (
            <ToggleSwitch checked={form.is_active} onChange={(checked) => setForm({ ...form, is_active: checked })} />
          )}
        </div>
      </div>

      <div className="card">
        <div className="box-label">Assigned Batches</div>
        {user.assigned_batches.length === 0 ? (
          <p style={{ fontSize: 12.5, color: 'var(--muted)' }}>No batches assigned to this user.</p>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Batch Name</th><th>College</th><th>Candidates</th><th>Status</th><th></th></tr></thead>
              <tbody>
                {user.assigned_batches.map((b) => (
                  <tr key={b.batch_id}>
                    <td>{b.batch_name}</td>
                    <td>{b.college_name}</td>
                    <td>{b.total_candidates}</td>
                    <td><span className={`pill ${BATCH_STATUS_PILL[b.status] || 'gray'}`}>{b.status_display}</span></td>
                    <td><Link to={`/batches/${b.batch_id}`} className="link-text">View</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="btn-row" style={{ display: 'flex', gap: 10, marginTop: 8 }}>
        <button className="btn" onClick={() => navigate('/admin/users')}>Cancel</button>
        <button className="btn primary" onClick={handleSave} disabled={saving}>
          <ButtonSpinner loading={saving}>💾 Save Changes</ButtonSpinner>
        </button>
        {!isSelf && (
          <button className="btn danger" style={{ marginLeft: 'auto' }}
                  onClick={() => setDeactivateOpen(true)} disabled={!user.is_active}>
            {user.is_active ? 'Deactivate User' : 'Already Inactive'}
          </button>
        )}
      </div>

      {deactivateOpen && (
        <DeactivateUserModal
          user={user}
          onClose={() => setDeactivateOpen(false)}
          onDeactivated={() => navigate('/admin/users')}
        />
      )}
    </div>
  );
}
