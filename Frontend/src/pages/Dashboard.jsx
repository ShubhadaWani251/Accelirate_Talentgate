import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useSelector } from 'react-redux';
import toast from 'react-hot-toast';
import { LuChevronRight, LuCircleCheckBig, LuLayers, LuSearch, LuTrendingUp, LuTrophy, LuUsers } from 'react-icons/lu';
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
import DeleteDraftBatchModal from '../features/batches/DeleteDraftBatchModal';

const STATUS_PILL = { draft: 'gray', in_progress: 'blue', completed: 'green', cancelled: 'red' };

// The four numbers the dashboard endpoint returns, each with its own count of what arrived in
// the last seven days (serializers/dashboard._build_stats).
//
// Worded "+N this week", not the reference design's "N more than last week". For a running
// total those mean the same thing, and this is the one that says what was actually measured:
// the figure counts rows whose timestamp falls in the window, because no previous-period
// snapshot is stored for anything to be compared against.
// All four describe the work currently running - candidates sitting in a batch that is In
// Progress (see serializers/dashboard.build_dashboard_summary, which scopes the numbers the same
// way). Each link carries that scope as `batch_status`, so following a card lands on exactly the
// rows it counted rather than on a longer list the reader has to re-filter themselves.
//
// Completed is `status=completed`, which the candidates endpoint resolves through the latest
// attempt rather than Candidate.status - nothing ever writes COMPLETED to that field. Before
// this, the link already said status=completed and the endpoint simply ignored it, so the card
// led to an unfiltered list.
const STAT_CARDS = [
  { key: 'active_batches', label: 'Active Batches', to: '/batches', Icon: LuLayers, tone: 'blue' },
  { key: 'total_candidates', label: 'Total Candidates', to: '/candidates?batch_status=in_progress', Icon: LuUsers, tone: 'indigo' },
  { key: 'completed', label: 'Completed', to: '/candidates?batch_status=in_progress&status=completed', Icon: LuCircleCheckBig, tone: 'violet' },
  { key: 'total_pass', label: 'Passed', to: '/candidates?batch_status=in_progress&result=pass', Icon: LuTrophy, tone: 'green' },
];

const RESULT_BANDS = [
  { key: 'pass_count', label: 'Pass', tone: 'green' },
  { key: 'fail_count', label: 'Fail', tone: 'red' },
  { key: 'borderline_count', label: 'Borderline', tone: 'amber' },
];

function ResultsSummary({ batches }) {
  // Summed from the batch rows already on screen rather than from a new endpoint - every batch
  // carries its own pass/fail/borderline counts and the whole list is sent, not a page of it.
  //
  // It therefore describes the batches CURRENTLY FILTERED, not all time, because that list
  // follows the Batch Status filter below. The caption says so: a total that silently changes
  // when a filter moves is worse than one that admits its own scope.
  const totals = RESULT_BANDS.map(({ key, label, tone }) => ({
    label,
    tone,
    value: (batches || []).reduce((sum, b) => sum + (b[key] || 0), 0),
  }));
  const graded = totals.reduce((sum, t) => sum + t.value, 0);

  return (
    <div className="stat-card results-summary">
      <div className="stat-lbl">Results Summary</div>
      {graded === 0 ? (
        <div className="results-empty">No graded results in these batches yet.</div>
      ) : (
        <>
          <div className="results-bar" role="img"
               aria-label={totals.map((t) => `${t.label} ${t.value}`).join(', ')}>
            {totals.filter((t) => t.value > 0).map((t) => (
              <span key={t.label} className={`results-seg tone-${t.tone}`}
                    style={{ width: `${(t.value / graded) * 100}%` }} />
            ))}
          </div>
          <div className="results-legend">
            {totals.map((t) => (
              <div key={t.label} className="results-item">
                <span className={`results-dot tone-${t.tone}`} />
                <span className="results-item-label">{t.label}</span>
                <span className="results-item-value">{t.value}</span>
                <span className="results-item-pct">
                  {((t.value / graded) * 100).toFixed(1)}%
                </span>
              </div>
            ))}
          </div>
          <div className="results-scope">across the batches shown below</div>
        </>
      )}
    </div>
  );
}
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
  // Filters the rows already loaded rather than re-querying: the dashboard sends every batch for
  // the selected status, not a page of them, so there is nothing further to fetch and no reason
  // to make typing wait on the network.
  const [batchSearch, setBatchSearch] = useState('');
  const [tableLoading, setTableLoading] = useState(false);
  const [loadError, setLoadError] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  // The batch a delete is pending confirmation for - only ever a Draft row (see the button
  // below), so DeleteDraftBatchModal never has to guard against a non-draft target itself.
  const [deleteTarget, setDeleteTarget] = useState(null);

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

  // Matched against exactly the fields this table shows, with no exceptions, so every hit has a
  // visible reason for being in the list. college_name was briefly included and is not any more:
  // it is real data, but there is no college column here, so matching on it returned rows the
  // reader could not account for - and the placeholder then had to name a column that does not
  // exist to explain them.
  const query = batchSearch.trim().toLowerCase();
  const visibleBatches = query
    ? (batches || []).filter((b) => [
        b.batch_name, b.status_display, b.primary_ta_user_name,
      ].some((field) => (field || '').toLowerCase().includes(query)))
    : (batches || []);

  return (
    <div>
      <h3>{isAdmin ? 'Administrator Dashboard' : 'TA Dashboard'}</h3>
      {/* The second sentence is not decoration. "Total Candidates" over a scoped figure reads as
          every candidate who has ever been uploaded, so the scope has to be stated once, here,
          where it governs the whole row below. */}
      <div className="page-sub">
        Overview of your aptitude test batches and candidate performance.
        {' '}Figures below cover batches that are currently In Progress.
      </div>

      <div className="stat-row">
        {STAT_CARDS.map(({ key, label, to, Icon, tone }) => (
          // Each card links to where its number comes from, which is what the chevron promises.
          <Link key={key} to={to} className={`stat-card tone-${tone}`}>
            <span className="stat-icon"><Icon aria-hidden="true" /></span>
            <span className="stat-text">
              <span className="stat-lbl">{label}</span>
              <span className="stat-num">{stats[key]}</span>
              {/* Hidden at zero rather than shown as "+0 this week": a quiet week is not news,
                  and a row of zeroes would train people to stop reading the line entirely. */}
              {stats[`${key}_this_week`] > 0 && (
                <span className="stat-trend">
                  <LuTrendingUp aria-hidden="true" /> +{stats[`${key}_this_week`]} this week
                </span>
              )}
            </span>
            <LuChevronRight className="stat-chevron" aria-hidden="true" />
          </Link>
        ))}
        <ResultsSummary batches={visibleBatches} />
      </div>

      <div className="btn-row" style={{ display: 'flex', gap: 10, marginBottom: 20 }}>
        <Link to="/batches/new" className="btn primary">
          + Create Batch
        </Link>
        <Link to="/candidates" className="btn">
          View All Candidates
        </Link>
        <button className="btn" onClick={() => setExportOpen(true)}>⬇ Export All Candidates (Excel)</button>
        {/* Admin-only: this sets the exam schedule/question counts/cutoffs every NEW batch is
            created with (services/batch_defaults.py on the backend). Deliberately not reachable
            by a TA, and no longer buried inside the upload wizard - a change here has a bigger
            blast radius (every future batch, org-wide) than any one TA's own work. */}
        {isAdmin && (
          <Link to="/admin/default-batch-config" className="btn">
            ⚙ Configure Default Batch
          </Link>
        )}
      </div>

      {exportOpen && <ExportModal onClose={() => setExportOpen(false)} />}

      <div className="card" style={{ marginBottom: 20 }}>
        <div className="panel-head">
          <div className="panel-head-text">
            <div className="box-label" style={{ marginBottom: 0 }}>Batches Overview</div>
            {/* The old heading's "— status & results in one place" suffix is not repeated here.
                The table immediately below has Status, Pass, Fail and Borderline columns, so the
                sentence was describing something already on screen - and at this width it pushed
                the search and filters onto a second line. */}
            <div className="box-sub">View and manage all your aptitude test batches</div>
          </div>
          <div className="batch-controls">
            <div className="search-field">
              <LuSearch className="search-icon" aria-hidden="true" />
              <input
                type="search"
                className="search-input"
                value={batchSearch}
                onChange={(e) => setBatchSearch(e.target.value)}
                placeholder="Search name, owner or status…"
                aria-label="Search batches"
              />
            </div>
            <BatchStatusFilter value={batchStatus} onChange={handleStatusChange} />
          </div>
        </div>
        {/* aria-busy on the scroll container, so a filter change is announced once rather than
            per skeleton cell. */}
        <div className="table-scroll" aria-busy={tableLoading}>
          <table className="data-table">
            <thead>
              <tr>
                <th>Batch Name</th>
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
                <SkeletonTableRows rows={5} columns={isAdmin ? 9 : 8} />
              ) : visibleBatches.length === 0 ? (
                // Two different nothings: no batches in this status at all, versus batches that
                // exist but none matching what was typed. Showing the status message for a failed
                // search reads as if the filter were broken.
                <tr><td colSpan={isAdmin ? 9 : 8}>
                  {query
                    ? `No batches match "${batchSearch.trim()}".`
                    : EMPTY_MESSAGE[batchStatus] || 'No batches yet.'}
                </td></tr>
              ) : (
                visibleBatches.map((b) => (
                  <tr key={b.batch_id}>
                    <td>{b.batch_name}</td>
                    {isAdmin && <td>{b.primary_ta_user_name}</td>}
                    <td>{b.total_candidates}</td>
                    <td><span className={`pill ${STATUS_PILL[b.status] || 'gray'}`}>{b.status_display}</span></td>
                    <td>{b.pass_count}</td>
                    <td>{b.fail_count}</td>
                    {/* Candidates who cleared most sections and missed the rest by a single mark, waiting on a
                        TA's pass/fail decision - they are counted in neither column above. */}
                    <td>{b.borderline_count}</td>
                    <td style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
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
                      {b.status === 'draft' && (
                        <button
                          type="button"
                          className="link-text"
                          style={{ color: 'var(--brand-red)' }}
                          onClick={() => setDeleteTarget(b)}
                        >
                          Delete
                        </button>
                      )}
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
                <thead><tr><th>Section</th><th>Total Active Questions</th></tr></thead>
                <tbody>
                  {qbankHealth.map((s) => (
                    <tr key={s.section_name}>
                      <td>{s.section_name}</td>
                      {/* Distinct questions, not row count - a section can hold 84 rows of 6
                          questions, which won't fill a 10-question section. Just the count per
                          request; min_required_active rides along as a tooltip so the "min. 50
                          active each" in the box label still means something without a separate
                          Status column spelling out OK/Low for every row. */}
                      <td title={`Minimum required: ${s.min_required_active}`}>{s.active_count}</td>
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

      {deleteTarget && (
        <DeleteDraftBatchModal
          batch={deleteTarget}
          onClose={() => setDeleteTarget(null)}
          onDeleted={() => {
            setDeleteTarget(null);
            loadSummary(batchStatus);
          }}
        />
      )}
    </div>
  );
}
