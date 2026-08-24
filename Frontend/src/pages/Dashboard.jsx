import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useSelector } from 'react-redux';
import toast from 'react-hot-toast';
import { selectRoleCode } from '../features/auth/authSlice';
import * as dashboardApi from '../api/dashboardApi';
import * as candidateApi from '../api/candidateApi';
import ExportModal from '../features/candidates/ExportModal';
import BatchStatusFilter from '../components/common/BatchStatusFilter';
import ServerErrorPage from '../components/error/ServerErrorPage';
import {
  Skeleton, SkeletonPage, SkeletonStatCard, SkeletonTable, SkeletonTableRows,
} from '../components/loading/Skeleton';
import { extractErrorMessage } from '../utils/passwordSchema';

const STATUS_PILL = { draft: 'gray', in_progress: 'blue', completed: 'green', cancelled: 'red' };
const EMPTY_MESSAGE = {
  active: 'No active batches found.',
  draft: 'No Draft batches found.',
  cancelled: 'No Cancelled batches found.',
  all: 'No batches yet.',
};

export default function Dashboard() {
  const roleCode = useSelector(selectRoleCode);
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [batchStatus, setBatchStatus] = useState('active');
  const [tableLoading, setTableLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);

  async function loadSummary(status, { initial = false } = {}) {
    if (initial) setLoading(true); else setTableLoading(true);
    try {
      setSummary(await dashboardApi.getDashboardSummary(status));
      setLoadError(false);
    } catch (err) {
      toast.error(extractErrorMessage(err));
      // Without this the page fell through to its "Loading…" branch forever on a failed initial
      // load, because summary stayed null - a permanent fake loading state with no way out.
      if (initial) setLoadError(true);   // dashboard has no single 'resource', so 5xx-or-worse only
    } finally {
      if (initial) setLoading(false); else setTableLoading(false);
    }
  }

  useEffect(() => {
    loadSummary('active', { initial: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function handleStatusChange(status) {
    setBatchStatus(status);
    loadSummary(status);
  }

  async function handleExportBatch(batchId) {
    try {
      await candidateApi.exportCandidates({ batchId });
    } catch (err) {
      toast.error(extractErrorMessage(err));
    }
  }

  const isAdmin = roleCode === 'admin';

  // Error takes precedence over loading: once a load has failed there is nothing still coming.
  if (loadError) {
    return <ServerErrorPage onRetry={() => loadSummary(batchStatus, { initial: true })} />;
  }

  if (loading || !summary) {
    return (
      <SkeletonPage label="Loading dashboard…">
        <div className="grid-4" style={{ marginBottom: 20 }}>
          {Array.from({ length: 4 }).map((_, i) => <SkeletonStatCard key={i} />)}
        </div>
        <div className="btn-row" style={{ display: 'flex', gap: 10, marginBottom: 20, flexWrap: 'wrap' }}>
          <Skeleton width={190} height={38} radius={999} />
          <Skeleton width={160} height={38} radius={999} />
          <Skeleton width={210} height={38} radius={999} />
        </div>
        <div className="card" style={{ marginBottom: 20 }}>
          <Skeleton width="42%" height={11} style={{ marginBottom: 14 }} />
          <SkeletonTable rows={5} columns={isAdmin ? 10 : 9} label="Loading batches…" />
        </div>
      </SkeletonPage>
    );
  }

  const { stats, batches_overview: batches, question_bank_health: qbankHealth, ta_accounts: taAccounts } = summary;

  return (
    <div>
      <h3>{isAdmin ? 'Administrator Dashboard' : 'TA Dashboard'}</h3>

      <div className="grid-4" style={{ marginBottom: 20 }}>
        <div className="stat-card"><div className="stat-num">{stats.active_batches}</div><div className="stat-lbl">Active Batches</div></div>
        <div className="stat-card"><div className="stat-num">{stats.total_candidates}</div><div className="stat-lbl">Total Candidates</div></div>
        <div className="stat-card"><div className="stat-num">{stats.completed}</div><div className="stat-lbl">Completed</div></div>
        <div className="stat-card"><div className="stat-num">{stats.total_pass}</div><div className="stat-lbl">Total Pass Students</div></div>
      </div>

      <div className="btn-row" style={{ display: 'flex', gap: 10, marginBottom: 20 }}>
        <Link to="/batches/new" className="btn primary">
          + Upload New Candidates
        </Link>
        <Link to="/candidates" className="btn">
          View All Candidates
        </Link>
        <button className="btn" onClick={() => setExportOpen(true)}>⬇ Export All Candidates (Excel)</button>
      </div>

      {exportOpen && <ExportModal onClose={() => setExportOpen(false)} />}

      <div className="card" style={{ marginBottom: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                     flexWrap: 'wrap', gap: 10, marginBottom: 10 }}>
          <div className="box-label" style={{ marginBottom: 0 }}>
            Batches Overview — status &amp; results in one place
          </div>
          <BatchStatusFilter value={batchStatus} onChange={handleStatusChange} />
        </div>
        {/* aria-busy on the scroll container, so a filter change is announced once rather than
            per skeleton cell. */}
        <div className="table-scroll" aria-busy={tableLoading}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Batch Name</th>
                <th>College</th>
                {isAdmin && <th>TA Owner</th>}
                <th>Candidates</th>
                <th>Status</th>
                <th>Pass</th>
                <th>Fail</th>
                <th>Borderline</th>
                <th></th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {/* Skeleton rows rather than dimming the old rows: after a filter change the
                  previous rows belong to a different filter, so showing them faded reads as if
                  they were the (wrong) result. */}
              {tableLoading ? (
                <SkeletonTableRows rows={5} columns={isAdmin ? 10 : 9} />
              ) : batches.length === 0 ? (
                <tr><td colSpan={isAdmin ? 9 : 8}>{EMPTY_MESSAGE[batchStatus] || 'No batches yet.'}</td></tr>
              ) : (
                batches.map((b) => (
                  <tr key={b.batch_id}>
                    <td>{b.batch_name}</td>
                    <td>{b.college_name}</td>
                    {isAdmin && <td>{b.primary_ta_user_name}</td>}
                    <td>{b.total_candidates}</td>
                    <td><span className={`pill ${STATUS_PILL[b.status] || 'gray'}`}>{b.status_display}</span></td>
                    <td>{b.pass_count}</td>
                    <td>{b.fail_count}</td>
                    <td>{b.borderline_count}</td>
                    <td>
                      {/* Opens that batch's own page, not a filtered All Candidates view -
                          Batch Details is where the batch's config, actions and candidates live.
                          Drafts are filtered out server-side; the fallback is here so that if one
                          ever surfaces it resumes the upload wizard rather than opening an empty
                          details page. */}
                      <Link
                        className="link-text"
                        to={b.status === 'draft' ? `/batches/${b.batch_id}/continue` : `/batches/${b.batch_id}`}
                      >
                        {b.status === 'draft' ? 'Continue' : 'View'}
                      </Link>
                    </td>
                    <td>
                      <span className="link-text" onClick={() => handleExportBatch(b.batch_id)}>Export</span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {isAdmin && (
        <div className="grid-2">
          <div className="card">
            <div className="box-label">Question Bank Health (min. 50 active each)</div>
            {qbankHealth.length === 0 ? (
              <p style={{ color: 'var(--muted)', fontSize: 12.5 }}>No sections configured yet.</p>
            ) : (
              // Wrapped in .table-scroll like every other table: without it the table sets its
              // own intrinsic width and pushes the whole page sideways on a phone.
              <div className="table-scroll">
              <table className="data-table">
                <thead><tr><th>Section</th><th>Total Questions</th><th>Duplicates</th><th>Status</th></tr></thead>
                <tbody>
                  {qbankHealth.map((s) => (
                    <tr key={s.section_name}>
                      <td>{s.section_name}</td>
                      {/* Distinct questions, not row count - a section can hold 84 rows of 6
                          questions, which won't fill a 10-question section. Just the count per
                          request; the /min_required_active context still rides along as a
                          tooltip since the Status pill alone doesn't say how far short it is. */}
                      <td title={`Minimum required: ${s.min_required_active}`}>{s.active_count}</td>
                      <td>{s.duplicate_count > 0
                        ? <span className="pill amber">{s.duplicate_count}</span>
                        : '—'}</td>
                      <td><span className={`pill ${s.is_ok ? 'green' : 'red'}`}>{s.is_ok ? 'OK' : 'Low'}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              </div>
            )}
            <Link to="/admin/question-bank" className="link-text" style={{ display: 'inline-block', marginTop: 10 }}>
              Manage Question Bank →
            </Link>
          </div>
          <div className="card">
            <div className="box-label">TA Accounts</div>
            <div className="table-scroll">
              <table className="data-table">
                <thead><tr><th>Name</th><th>Status</th></tr></thead>
                <tbody>
                  {taAccounts.map((u) => (
                    <tr key={u.user_id}>
                      <td>{u.full_name}</td>
                      <td><span className={`pill ${u.role_name === 'Administrator' ? 'gray' : 'green'}`}>{u.role_name}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Link to="/admin/users" className="link-text" style={{ display: 'inline-block', marginTop: 10 }}>
              Manage Users →
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}
