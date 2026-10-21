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
const STATUS_PILL = { active: 'green', invited: 'amber', deactivated: 'gray' };

// The filter's options. "All" is deliberately first and the default: this list is short, and
// landing on a filtered view would hide accounts an administrator came here to find.
const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  { value: 'invited', label: 'Invited' },
  { value: 'active', label: 'Active' },
  { value: 'deactivated', label: 'Deactivated' },
];

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
  const [statusFilter, setStatusFilter] = useState('');

  async function refresh(p = page, status = statusFilter) {
    setLoading(true);
    try {
      const data = await userApi.listUsers({ page: p, status });
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
        {/* First and Last Name together on one row. They used to be split across two rows with
            Corporate Email between them, so the two halves of one person's name were read and
            typed as if they were unrelated fields. */}
        <div className="grid-2-compact">
          <div className="field">
            <label>First Name</label>
            <input placeholder="First name" value={form.first_name}
                   onChange={(e) => set('first_name', e.target.value)} />
          </div>
          <div className="field">
            <label>Last Name</label>
            <input placeholder="Last name" value={form.last_name}
                   onChange={(e) => set('last_name', e.target.value)} />
          </div>
        </div>
        <div className="grid-2">
          <div className="field">
            <label>Corporate Email</label>
            <input placeholder="name@company.com" value={form.email}
                   onChange={(e) => set('email', e.target.value)} />
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

      {/* Filtering happens server-side, so it narrows every page rather than only the rows
          currently loaded - see views/users.STATUS_FILTERS. Resets to page 1, since page 4 of
          an unfiltered list is usually past the end of a filtered one. */}
      <div className="panel-head" style={{ marginBottom: 12 }}>
        <div className="panel-head-text">
          <div className="box-label" style={{ marginBottom: 0 }}>Users</div>
        </div>
        <div className="field" style={{ margin: 0, minWidth: 180 }}>
          <label htmlFor="user-status-filter">Status</label>
          <select
            id="user-status-filter"
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); refresh(1, e.target.value); }}
          >
            {STATUS_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
        </div>
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
              // Two different nothings: no users at all, versus none in the chosen status.
              // The first reading would make a working filter look like a broken list.
              <tr><td colSpan={5}>
                {statusFilter
                  ? `No ${STATUS_OPTIONS.find((o) => o.value === statusFilter)?.label.toLowerCase()} users.`
                  : 'No users yet.'}
              </td></tr>
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
