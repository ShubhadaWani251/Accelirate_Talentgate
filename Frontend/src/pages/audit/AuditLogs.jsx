import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import * as auditApi from '../../api/auditApi';
import PaginationControls from '../../components/common/PaginationControls';
import { ListPageSkeleton, SkeletonTableRows } from '../../components/loading/Skeleton';
import { extractErrorMessage } from '../../utils/passwordSchema';

const EMPTY_FILTERS = { user: '', action: '', entity: '', search: '', date_from: '', date_to: '' };

// A failed sign-in is the one action worth colouring - it is the thing an administrator is
// scanning for. Everything else is routine activity and shouldn't compete for attention.
const ROW_TONE = { login_failed: 'var(--brand-red)' };

// Admin-only oversight screen: every action any user has taken, newest first. The human wording
// for each row (action page, description) is built server-side in serializers/audit.py rather
// than here, so an export or report would say exactly the same thing as this table.
export default function AuditLogs() {
  const [logs, setLogs] = useState([]);
  const [page, setPage] = useState(1);
  const [pageMeta, setPageMeta] = useState({ count: 0, next: null, previous: null });
  const [loading, setLoading] = useState(true);
  const [firstLoad, setFirstLoad] = useState(true);
  const [filters, setFilters] = useState(EMPTY_FILTERS);
  const [options, setOptions] = useState({ actions: [], entities: [], users: [] });

  async function refresh(f = filters, p = page) {
    setLoading(true);
    try {
      const data = await auditApi.listAuditLogs(f, p);
      setLogs(data.results);
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
    // Filter options are fetched once - they come from what's in the table, so they change only
    // when a genuinely new kind of action occurs.
    auditApi.getAuditFilterOptions().then(setOptions).catch(() => {
      // Non-fatal: the table still works with free-text search if the dropdowns can't load.
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function set(field, value) {
    setFilters({ ...filters, [field]: value });
  }

  function applyFilters() {
    refresh(filters, 1);
  }

  function clearFilters() {
    setFilters(EMPTY_FILTERS);
    refresh(EMPTY_FILTERS, 1);
  }

  if (firstLoad && loading) {
    return (
      <ListPageSkeleton
        titleWidth={180} actions={0} filters={4} rows={8} columns={4}
        label="Loading audit log…"
      />
    );
  }

  const selectStyle = {
    padding: '9px 12px', borderRadius: 8, border: '1px solid var(--line-soft)', minWidth: 150,
  };

  return (
    <div>
      <h3>Audit Log</h3>
      <div className="alert" style={{ marginBottom: 12 }}>
        Every action taken in the application, newest first — who did it, where, and what
        happened. This record is append-only and cannot be edited or deleted from here.
      </div>

      <div className="card">
        <div className="box-label">Filters</div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'flex-end' }}>
          <div className="field" style={{ margin: 0 }}>
            <label>User</label>
            <select value={filters.user} onChange={(e) => set('user', e.target.value)} style={selectStyle}>
              <option value="">All users</option>
              {options.users.map((u) => (
                <option key={u.value} value={u.value}>{u.label}</option>
              ))}
            </select>
          </div>
          <div className="field" style={{ margin: 0 }}>
            <label>Action</label>
            <select value={filters.action} onChange={(e) => set('action', e.target.value)} style={selectStyle}>
              <option value="">All actions</option>
              {options.actions.map((a) => (
                <option key={a.value} value={a.value}>{a.label}</option>
              ))}
            </select>
          </div>
          <div className="field" style={{ margin: 0 }}>
            <label>Area</label>
            <select value={filters.entity} onChange={(e) => set('entity', e.target.value)} style={selectStyle}>
              <option value="">All areas</option>
              {options.entities.map((x) => (
                <option key={x.value} value={x.value}>{x.label}</option>
              ))}
            </select>
          </div>
          <div className="field" style={{ margin: 0 }}>
            <label>From</label>
            <input type="date" value={filters.date_from}
                   onChange={(e) => set('date_from', e.target.value)} style={selectStyle} />
          </div>
          <div className="field" style={{ margin: 0 }}>
            <label>To</label>
            <input type="date" value={filters.date_to}
                   onChange={(e) => set('date_to', e.target.value)} style={selectStyle} />
          </div>
          <div className="field" style={{ margin: 0, flex: 1, minWidth: 200 }}>
            <label>Search</label>
            <input
              placeholder="Name, email or action…"
              value={filters.search}
              onChange={(e) => set('search', e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && applyFilters()}
              style={{ ...selectStyle, width: '100%' }}
            />
          </div>
        </div>
        <div className="btn-row" style={{ marginTop: 12, display: 'flex', gap: 8 }}>
          <button className="btn primary" onClick={applyFilters}>Apply Filters</button>
          <button className="btn" onClick={clearFilters}>Clear Filters</button>
        </div>
      </div>

      <div className="table-scroll" aria-busy={loading}>
        <table className="data-table">
          <thead>
            <tr>
              <th>Date &amp; Time</th>
              <th>User</th>
              <th>Action Page</th>
              <th>Action Description</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <SkeletonTableRows rows={8} columns={4} />
            ) : logs.length === 0 ? (
              <tr><td colSpan={4}>No activity matches these filters.</td></tr>
            ) : (
              logs.map((row) => (
                <tr key={row.log_id}>
                  {/* Rendered in the viewer's own timezone - the API sends a UTC instant, so no
                      manual offset arithmetic here. */}
                  <td style={{ whiteSpace: 'nowrap' }}>
                    {new Date(row.created_at).toLocaleString(undefined, {
                      day: 'numeric', month: 'short', year: 'numeric',
                      hour: 'numeric', minute: '2-digit', second: '2-digit',
                    })}
                  </td>
                  <td>
                    {row.user_name}
                    {row.user_email && (
                      <div style={{ fontSize: 11, color: 'var(--muted)' }}>{row.user_email}</div>
                    )}
                  </td>
                  <td>{row.action_page}</td>
                  <td style={{ whiteSpace: 'normal', color: ROW_TONE[row.action_type] }}>
                    {row.action_description}
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
        onPrev={() => refresh(filters, page - 1)}
        onNext={() => refresh(filters, page + 1)}
        onPageChange={(p) => refresh(filters, p)}
      />
    </div>
  );
}
