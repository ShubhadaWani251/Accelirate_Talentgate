import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useSelector } from 'react-redux';
import toast from 'react-hot-toast';
import * as userApi from '../../api/userApi';
import { selectUser } from '../../features/auth/authSlice';
import DeactivateUserModal from '../../features/users/DeactivateUserModal';
import PaginationControls from '../../components/common/PaginationControls';
import { ListPageSkeleton, SkeletonTableRows } from '../../components/loading/Skeleton';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';

const ROLE_PILL = { admin: 'gray', ta: 'blue' };

// Amber for Invited on purpose: it is neither finished nor wrong, it is waiting on someone -
// the same reading .pill.amber carries everywhere else in this app.
const STATUS_PILL = { active: 'green', invited: 'amber', inactive: 'gray' };

// Said at the point of the attempt, not after it. The backend enforces this too
// (views/users.SELF_DEACTIVATION_MESSAGE); this is so nobody has to click to find out.
const SELF_DEACTIVATE_NOTE =
  "You can't deactivate your own account. Another administrator can do it for you.";

export default function UserManagement() {
  const currentUser = useSelector(selectUser);
  const [users, setUsers] = useState([]);
  const [page, setPage] = useState(1);
  const [pageMeta, setPageMeta] = useState({ count: 0, next: null, previous: null });
  const [loading, setLoading] = useState(true);
  // Page-level skeleton on first paint only; pagination keeps the chrome and skeletons the rows.
  const [firstLoad, setFirstLoad] = useState(true);
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
      setFirstLoad(false);
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

  if (firstLoad && loading) {
    return (
      <ListPageSkeleton
        titleWidth={250} actions={0} filters={0} rows={5} columns={5}
        label="Loading users…"
      />
    );
  }

  return (
    <div>
      <h3>User &amp; Access Management</h3>

      <div className="card">
        <div className="box-label">Add User</div>
        <div className="grid-2">
          <div className="field">
            <label>First Name</label>
            <input placeholder="First name" value={form.first_name}
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
            <input placeholder="Last name" value={form.last_name}
                   onChange={(e) => set('last_name', e.target.value)} />
          </div>
          <div className="field">
            <label>Role</label>
            <select value={form.role} onChange={(e) => set('role', e.target.value)}>
              <option value="ta">Staffing User</option>
              <option value="admin">Administrator</option>
            </select>
          </div>
        </div>
        <button className="btn primary" onClick={handleCreate}
                disabled={creating || !form.first_name || !form.email}>
          <ButtonSpinner loading={creating}>+ Create User</ButtonSpinner>
        </button>
      </div>

      <div className="table-scroll" aria-busy={loading}>
        <table className="data-table">
          <thead>
            <tr><th>Name</th><th>Corporate Email</th><th>Role</th><th>Status</th><th></th></tr>
          </thead>
          <tbody>
            {loading ? (
              <SkeletonTableRows rows={5} columns={5} />
            ) : users.length === 0 ? (
              <tr><td colSpan={5}>No users yet.</td></tr>
            ) : (
              users.map((u) => (
                <tr key={u.user_id}>
                  <td>{u.full_name}</td>
                  <td>{u.email}</td>
                  <td><span className={`pill ${ROLE_PILL[u.role_code] || 'gray'}`}>{u.role_name}</span></td>
                  {/* The derived three-state status, not the raw is_active boolean: a user who
                      has been emailed credentials but never set their own password reads as
                      Invited, where this used to claim they were Active. */}
                  <td>
                    <span className={`pill ${STATUS_PILL[u.status] || 'gray'}`}>
                      {u.status_display}
                    </span>
                  </td>
                  <td style={{ display: 'flex', gap: 12 }}>
                    <Link to={`/admin/users/${u.user_id}`} className="link-text">Edit access</Link>
                    {/* Edit User already refuses to show this for your own account; this list
                        offered it on every row, which is the one place an administrator could
                        actually try to switch themselves off. Shown but inert, rather than
                        removed, so the reason is on screen instead of only in a failed
                        request. */}
                    {u.user_id === currentUser?.user_id ? (
                      <span
                        className="link-text"
                        style={{ color: 'var(--muted)', cursor: 'not-allowed' }}
                        title={SELF_DEACTIVATE_NOTE}
                        aria-disabled="true"
                      >
                        Deactivate
                      </span>
                    ) : u.is_active ? (
                      <button className="link-text" style={{ color: 'var(--brand-red)' }} onClick={() => setDeactivateTarget(u)}>
                        Deactivate
                      </button>
                    ) : null}
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
        onPageChange={(p) => refresh(p)}
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
