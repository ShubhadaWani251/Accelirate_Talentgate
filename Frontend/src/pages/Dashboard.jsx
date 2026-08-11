import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useSelector } from 'react-redux';
import toast from 'react-hot-toast';
import { selectRoleCode } from '../features/auth/authSlice';
import * as dashboardApi from '../api/dashboardApi';
import * as candidateApi from '../api/candidateApi';
import { extractErrorMessage } from '../utils/passwordSchema';

const STATUS_PILL = { draft: 'gray', in_progress: 'blue', completed: 'green' };

export default function Dashboard() {
  const roleCode = useSelector(selectRoleCode);
  const navigate = useNavigate();
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(true);
  const [exportOpen, setExportOpen] = useState(false);
  const [exportFrom, setExportFrom] = useState('');
  const [exportTo, setExportTo] = useState('');
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    dashboardApi.getDashboardSummary().then((data) => {
      setSummary(data);
      setLoading(false);
    });
  }, []);

  async function handleExportAll() {
    setExporting(true);
    try {
      await candidateApi.exportCandidates({ from: exportFrom || undefined, to: exportTo || undefined });
      setExportOpen(false);
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setExporting(false);
    }
  }

  async function handleExportBatch(batchId) {
    try {
      await candidateApi.exportCandidates({ batchId });
    } catch (err) {
      toast.error(extractErrorMessage(err));
    }
  }

  if (loading || !summary) return <div>Loading…</div>;

  const isAdmin = roleCode === 'admin';
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
        <Link to="/batches/new" className="btn primary" style={{ width: 'auto', textDecoration: 'none' }}>
          + Upload New Candidates
        </Link>
        <Link to="/candidates" className="btn" style={{ width: 'auto', textDecoration: 'none' }}>
          View All Candidates
        </Link>
        <button className="btn" onClick={() => setExportOpen(true)}>⬇ Export All Candidates (Excel)</button>
      </div>

      {exportOpen && (
        <div className="modal-overlay" onClick={() => setExportOpen(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <h4>Export Candidates</h4>
            <p>Select the date range for exporting candidate data (leave blank for all).</p>
            <div className="field">
              <label>From Date</label>
              <input type="date" value={exportFrom} onChange={(e) => setExportFrom(e.target.value)} />
            </div>
            <div className="field">
              <label>To Date</label>
              <input type="date" value={exportTo} onChange={(e) => setExportTo(e.target.value)} />
            </div>
            <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button className="btn" onClick={() => setExportOpen(false)}>Cancel</button>
              <button className="btn primary" style={{ width: 'auto' }} onClick={handleExportAll} disabled={exporting}>
                {exporting ? 'Exporting…' : 'Export'}
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="card" style={{ marginBottom: 20 }}>
        <div className="box-label">Batches Overview — status &amp; results in one place</div>
        <div className="table-scroll">
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
              {batches.length === 0 ? (
                <tr><td colSpan={isAdmin ? 9 : 8}>No batches yet.</td></tr>
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
                      <span className="link-text" onClick={() => navigate(`/candidates?batch=${b.batch_id}`)}>
                        View
                      </span>
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
              <table className="data-table">
                <thead><tr><th>Section</th><th>Active</th><th>Status</th></tr></thead>
                <tbody>
                  {qbankHealth.map((s) => (
                    <tr key={s.section_name}>
                      <td>{s.section_name}</td>
                      <td>{s.active_count}</td>
                      <td><span className={`pill ${s.is_ok ? 'green' : 'amber'}`}>{s.is_ok ? 'OK' : 'Low'}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
          <div className="card">
            <div className="box-label">TA Accounts</div>
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
        </div>
      )}
    </div>
  );
}
