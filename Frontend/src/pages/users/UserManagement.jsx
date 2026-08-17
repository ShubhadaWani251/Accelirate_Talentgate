import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import toast from 'react-hot-toast';
import * as userApi from '../../api/userApi';
import DeactivateUserModal from '../../features/users/DeactivateUserModal';
import PaginationControls from '../../components/common/PaginationControls';
import { extractErrorMessage } from '../../utils/passwordSchema';

const ROLE_PILL = { admin: 'gray', ta: 'blue' };

export default function UserManagement() {
  const [users, setUsers] = useState([]);
  const [page, setPage] = useState(1);
  const [pageMeta, setPageMeta] = useState({ count: 0, next: null, previous: null });
  const [loading, setLoading] = useState(true);
  const [form, setForm] = useState({ first_name: '', last_name: '', email: '', role: 'ta' });
  const [creating, setCreating] = useState(false);
  const [deactivateTarget, setDeactivateTarget] = useState(null);

  async function refresh(p = page) {
    setLoading(true);
    try {
      const data = await userApi.listUsers({ page: p });
      setUsers(data.results);
      setPageMeta({ count: data.count, next: data.next, previous: data.previous });
      setPage(p);
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function set(field, value) {
    setForm({ ...form, [field]: value });
  }

  async function handleCreate() {
    setCreating(true);
    try {
      await userApi.createUser(form);
      toast.success(`${form.first_name} created - credentials have been emailed to them.`);
      setForm({ first_name: '', last_name: '', email: '', role: 'ta' });
      refresh(1);
    } catch (err) {
      toast.error(extractErrorMessage(err, ['first_name', 'email', 'role']));
    } finally {
      setCreating(false);
    }
  }

  return (
    <div>
      <h3>User &amp; Access Management</h3>

      <div className="card">
        <div className="box-label">Add User</div>
        <div className="grid-2">
          <div className="field">
            <label>Name</label>
            <input placeholder="Full name" value={form.first_name}
                   onChange={(e) => set('first_name', e.target.value)} />
          </div>
          <div className="field">
            <label>Corporate Email</label>
            <input placeholder="name@company.com" value={form.email}
                   onChange={(e) => set('email', e.target.value)} />
          </div>
        </div>
        <div className="grid-2">
          <div className="field">
            <label>Last Name</label>
            <input value={form.last_name} onChange={(e) => set('last_name', e.target.value)} />
          </div>
          <div className="field">
            <label>Role</label>
            <select value={form.role} onChange={(e) => set('role', e.target.value)}>
              <option value="ta">Staffing User</option>
              <option value="admin">Administrator</option>
            </select>
          </div>
        </div>
        <button className="btn primary" style={{ width: 'auto' }} onClick={handleCreate}
                disabled={creating || !form.first_name || !form.email}>
          {creating ? 'Creating…' : '+ Create User'}
        </button>
      </div>

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr><th>Name</th><th>Corporate Email</th><th>Role</th><th>Status</th><th></th></tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5}>Loading…</td></tr>
            ) : users.length === 0 ? (
              <tr><td colSpan={5}>No users yet.</td></tr>
            ) : (
              users.map((u) => (
                <tr key={u.user_id}>
                  <td>{u.full_name}</td>
                  <td>{u.email}</td>
                  <td><span className={`pill ${ROLE_PILL[u.role_code] || 'gray'}`}>{u.role_name}</span></td>
                  <td><span className={`pill ${u.is_active ? 'green' : 'gray'}`}>{u.is_active ? 'Active' : 'Inactive'}</span></td>
                  <td style={{ display: 'flex', gap: 12 }}>
                    <Link to={`/admin/users/${u.user_id}`} className="link-text">Edit access</Link>
                    <button className="link-text" style={{ color: 'var(--brand-red)' }} onClick={() => setDeactivateTarget(u)}>
                      Deactivate
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <PaginationControls
        page={page}
        count={pageMeta.count}
        hasPrevious={Boolean(pageMeta.previous)}
        hasNext={Boolean(pageMeta.next)}
        onPrev={() => refresh(page - 1)}
        onNext={() => refresh(page + 1)}
      />

      {deactivateTarget && (
        <DeactivateUserModal
          user={deactivateTarget}
          onClose={() => setDeactivateTarget(null)}
          onDeactivated={() => { setDeactivateTarget(null); refresh(); }}
        />
      )}
    </div>
  );
}
