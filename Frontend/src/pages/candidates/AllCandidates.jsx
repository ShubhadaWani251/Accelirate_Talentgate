import { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import * as candidateApi from '../../api/candidateApi';
import * as batchApi from '../../api/batchApi';
import { extractErrorMessage } from '../../utils/passwordSchema';

const STATUS_PILL = {
  pending_invite: 'gray', invited: 'blue', in_progress: 'blue',
  completed: 'green', terminated: 'amber', no_show: 'gray',
};
const RESULT_PILL = { pending: 'gray', pass: 'green', fail: 'red' };

const NOTIFY_TEMPLATES = [
  { key: 'hold', label: '🕒 On Hold',
    text: 'Hi, thank you for completing the assessment. Your application is currently on hold pending further review — we will update you shortly.' },
  { key: 'cutoff', label: '📉 Cutoff Changed',
    text: 'Hi, please note the qualifying cutoff for your section has been revised. Your result is being re-evaluated against the updated cutoff.' },
  { key: 'shortlisted', label: '✅ Shortlisted',
    text: 'Congratulations! You have been shortlisted for the next round. Further details will follow by email shortly.' },
  { key: 'custom', label: '✍ Custom Message', text: '' },
];

const EMPTY_FILTERS = { name: '', email: '', aadhaar: '', batch_id: '', result: '', score_min: '', score_max: '' };

export default function AllCandidates() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [filters, setFilters] = useState({ ...EMPTY_FILTERS, batch_id: searchParams.get('batch') || '' });
  const [candidates, setCandidates] = useState([]);
  const [batches, setBatches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState(new Set());

  const [editingCandidate, setEditingCandidate] = useState(null);
  const [editForm, setEditForm] = useState({});
  const [saving, setSaving] = useState(false);
  const [resendConfirming, setResendConfirming] = useState(false);

  const [notifyOpen, setNotifyOpen] = useState(false);
  const [notifyMessage, setNotifyMessage] = useState('');
  const [notifying, setNotifying] = useState(false);

  const [exportOpen, setExportOpen] = useState(false);
  const [exportFrom, setExportFrom] = useState('');
  const [exportTo, setExportTo] = useState('');
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    batchApi.listBatches().then(setBatches);
  }, []);

  async function refresh(f = filters) {
    setLoading(true);
    try {
      setCandidates(await candidateApi.listCandidates(f));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const filterBatchName = useMemo(() => {
    if (!filters.batch_id) return null;
    return batches.find((b) => String(b.batch_id) === String(filters.batch_id))?.batch_name;
  }, [filters.batch_id, batches]);

  function clearBatchFilter() {
    const next = { ...filters, batch_id: '' };
    setFilters(next);
    setSearchParams({});
    refresh(next);
  }

  function applyFilters() {
    refresh(filters);
  }

  function clearFilters() {
    setFilters(EMPTY_FILTERS);
    setSearchParams({});
    refresh(EMPTY_FILTERS);
  }

  function toggleRow(id) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function toggleSelectAll() {
    setSelected((prev) => (prev.size === candidates.length ? new Set() : new Set(candidates.map((c) => c.candidate_id))));
  }

  function openEdit(candidate) {
    setEditingCandidate(candidate);
    setEditForm({
      first_name: candidate.full_name?.split(' ')[0] || '',
      last_name: candidate.full_name?.split(' ').slice(1).join(' ') || '',
      email: candidate.email,
      college_name: candidate.college_name || '',
      degree: candidate.degree || '',
      stream: candidate.stream || '',
      percentage: candidate.percentage ?? '',
      passing_out_year: candidate.passing_out_year ?? '',
      location: candidate.location || '',
    });
  }

  async function handleSaveEdit() {
    setSaving(true);
    try {
      await candidateApi.updateCandidate(editingCandidate.candidate_id, editForm);
      toast.success('Candidate updated.');
      setEditingCandidate(null);
      refresh();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function handleResendInvite() {
    setResendConfirming(false);
    try {
      const res = await candidateApi.resendInvite(editingCandidate.candidate_id);
      toast.success(res.detail);
      setEditingCandidate(null);
      refresh();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    }
  }

  async function handleSendNotification() {
    if (!notifyMessage.trim()) {
      toast.error('Write or pick a message first.');
      return;
    }
    setNotifying(true);
    try {
      const res = await candidateApi.notifyCandidates(
        Array.from(selected), 'Accelirate TalentGate - Update', notifyMessage
      );
      toast.success(`Notified ${res.notified_count} candidate(s).`);
      setNotifyOpen(false);
      setNotifyMessage('');
      setSelected(new Set());
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setNotifying(false);
    }
  }

  async function handleExport() {
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

  return (
    <div>
      <h3>All Candidates</h3>

      {filterBatchName && (
        <div className="alert" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 14 }}>
          <span>Showing candidates from <b>{filterBatchName}</b> only</span>
          <button className="btn small" onClick={clearBatchFilter}>Clear filter — show all batches</button>
        </div>
      )}

      <div className="card" style={{ marginBottom: 16 }}>
        <div className="box-label">Filters</div>
        <div className="grid-4">
          <div className="field">
            <label>Name</label>
            <input value={filters.name} onChange={(e) => setFilters({ ...filters, name: e.target.value })} placeholder="Search name…" />
          </div>
          <div className="field">
            <label>Email</label>
            <input value={filters.email} onChange={(e) => setFilters({ ...filters, email: e.target.value })} placeholder="Search email…" />
          </div>
          <div className="field">
            <label>Aadhaar</label>
            <input value={filters.aadhaar} onChange={(e) => setFilters({ ...filters, aadhaar: e.target.value })} placeholder="Search Aadhaar…" />
          </div>
          <div className="field">
            <label>Batch Name</label>
            <select value={filters.batch_id} onChange={(e) => setFilters({ ...filters, batch_id: e.target.value })}>
              <option value="">All Batches</option>
              {batches.map((b) => <option key={b.batch_id} value={b.batch_id}>{b.batch_name}</option>)}
            </select>
          </div>
        </div>
        <div className="grid-4" style={{ marginTop: 8 }}>
          <div className="field">
            <label>Result</label>
            <select value={filters.result} onChange={(e) => setFilters({ ...filters, result: e.target.value })}>
              <option value="">All (Pass / Fail)</option>
              <option value="pass">Pass</option>
              <option value="fail">Fail</option>
              <option value="pending">Pending</option>
            </select>
          </div>
          <div className="field">
            <label>Overall Score — From</label>
            <input type="number" value={filters.score_min} onChange={(e) => setFilters({ ...filters, score_min: e.target.value })} placeholder="e.g. 0" />
          </div>
          <div className="field">
            <label>Overall Score — To</label>
            <input type="number" value={filters.score_max} onChange={(e) => setFilters({ ...filters, score_max: e.target.value })} placeholder="e.g. 40" />
          </div>
          <div className="field">
            <label>&nbsp;</label>
            <div className="btn-row" style={{ display: 'flex', gap: 10, marginTop: 0 }}>
              <button className="btn" onClick={clearFilters}>Clear Filters</button>
              <button className="btn primary" style={{ width: 'auto' }} onClick={applyFilters}>Apply Filters</button>
            </div>
          </div>
        </div>
      </div>

      <div className="btn-row" style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 12 }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5 }}>
          <input type="checkbox" checked={selected.size === candidates.length && candidates.length > 0} onChange={toggleSelectAll} />
          <b>Select All</b>
        </label>
        <button className="btn" disabled={selected.size === 0} onClick={() => setNotifyOpen(true)}>
          ✉ Send Notification Email ({selected.size})
        </button>
        <button className="btn" style={{ marginLeft: 'auto' }} onClick={() => setExportOpen(true)}>
          ⬇ Export All Candidates (Excel)
        </button>
      </div>

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th></th><th>Name</th><th>Email</th><th>Batch Name</th><th>College</th><th>Degree</th>
              <th>Stream</th><th>Percentage</th><th>Passing Out Year</th><th>Location</th><th>Aadhaar</th>
              <th>Status</th><th>Logical</th><th>Quant.</th><th>Verbal</th><th>Programming</th>
              <th>Overall</th><th>Result</th><th></th><th></th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={20}>Loading…</td></tr>
            ) : candidates.length === 0 ? (
              <tr><td colSpan={20}>No candidates found.</td></tr>
            ) : (
              candidates.map((c) => (
                <tr key={c.candidate_id}>
                  <td><input type="checkbox" checked={selected.has(c.candidate_id)} onChange={() => toggleRow(c.candidate_id)} /></td>
                  <td>{c.full_name}</td>
                  <td>{c.email}</td>
                  <td>{c.batch_name}</td>
                  <td>{c.college_name || '—'}</td>
                  <td>{c.degree || '—'}</td>
                  <td>{c.stream || '—'}</td>
                  <td>{c.percentage != null ? `${c.percentage}%` : '—'}</td>
                  <td>{c.passing_out_year || '—'}</td>
                  <td>{c.location || '—'}</td>
                  <td>{c.aadhaar_masked || '—'}</td>
                  <td><span className={`pill ${STATUS_PILL[c.status] || 'gray'}`}>{c.status_display}</span></td>
                  <td>{c.logical_score ?? '—'}</td>
                  <td>{c.quantitative_score ?? '—'}</td>
                  <td>{c.verbal_score ?? '—'}</td>
                  <td>{c.programming_score ?? '—'}</td>
                  <td>{c.overall_score ?? '—'}</td>
                  <td><span className={`pill ${RESULT_PILL[c.result] || 'gray'}`}>{c.result_display}</span></td>
                  <td><Link className="link-text" to={`/candidates/${c.candidate_id}`}>View</Link></td>
                  <td><span className="link-text" onClick={() => openEdit(c)}>Edit</span></td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {editingCandidate && (
        <div className="modal-overlay" onClick={() => setEditingCandidate(null)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 430 }}>
            <h4>Edit Candidate Details</h4>
            <p>Update candidate information or resend the assessment invitation.</p>
            <div className="grid-2">
              <div className="field"><label>First Name</label><input value={editForm.first_name} onChange={(e) => setEditForm({ ...editForm, first_name: e.target.value })} /></div>
              <div className="field"><label>Last Name</label><input value={editForm.last_name} onChange={(e) => setEditForm({ ...editForm, last_name: e.target.value })} /></div>
            </div>
            <div className="field"><label>Email Address</label><input value={editForm.email} onChange={(e) => setEditForm({ ...editForm, email: e.target.value })} /></div>
            <div className="field"><label>College Name</label><input value={editForm.college_name} onChange={(e) => setEditForm({ ...editForm, college_name: e.target.value })} /></div>
            <div className="grid-2">
              <div className="field"><label>Degree</label><input value={editForm.degree} onChange={(e) => setEditForm({ ...editForm, degree: e.target.value })} /></div>
              <div className="field"><label>Stream</label><input value={editForm.stream} onChange={(e) => setEditForm({ ...editForm, stream: e.target.value })} /></div>
            </div>
            <div className="grid-2">
              <div className="field"><label>Percentage</label><input type="number" value={editForm.percentage} onChange={(e) => setEditForm({ ...editForm, percentage: e.target.value })} /></div>
              <div className="field"><label>Passing Out Year</label><input type="number" value={editForm.passing_out_year} onChange={(e) => setEditForm({ ...editForm, passing_out_year: e.target.value })} /></div>
            </div>
            <div className="field"><label>Location</label><input value={editForm.location} onChange={(e) => setEditForm({ ...editForm, location: e.target.value })} /></div>
            <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button className="btn" onClick={() => setEditingCandidate(null)}>Cancel</button>
              <button className="btn" onClick={() => setResendConfirming(true)}>📧 Send Invite Again</button>
              <button className="btn primary" style={{ width: 'auto' }} onClick={handleSaveEdit} disabled={saving}>
                {saving ? 'Saving…' : '💾 Save'}
              </button>
            </div>
          </div>
        </div>
      )}

      {resendConfirming && (
        <div className="modal-overlay" onClick={() => setResendConfirming(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 360 }}>
            <h4>Send Invite Again?</h4>
            <p>This will re-send the assessment invite link to {editingCandidate?.email}. Continue?</p>
            <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button className="btn" onClick={() => setResendConfirming(false)}>Cancel</button>
              <button className="btn primary" style={{ width: 'auto' }} onClick={handleResendInvite}>Confirm &amp; Send</button>
            </div>
          </div>
        </div>
      )}

      {notifyOpen && (
        <div className="modal-overlay" onClick={() => setNotifyOpen(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 440 }}>
            <h4>Notify Selected Candidates</h4>
            <p>Sends an email to every selected candidate. Pick a template, review or edit it, then send.</p>
            <div className="btn-row" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
              {NOTIFY_TEMPLATES.map((t) => (
                <button key={t.key} className="btn small" onClick={() => setNotifyMessage(t.text)}>{t.label}</button>
              ))}
            </div>
            <div className="field">
              <label>Message (editable)</label>
              <textarea rows={4} value={notifyMessage} onChange={(e) => setNotifyMessage(e.target.value)}
                placeholder="Select a template above, or write a custom message…" />
            </div>
            <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button className="btn" onClick={() => setNotifyOpen(false)}>Cancel</button>
              <button className="btn primary" style={{ width: 'auto' }} onClick={handleSendNotification} disabled={notifying}>
                {notifying ? 'Sending…' : '📧 Send Email'}
              </button>
            </div>
          </div>
        </div>
      )}

      {exportOpen && (
        <div className="modal-overlay" onClick={() => setExportOpen(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()}>
            <h4>Export Candidates</h4>
            <p>Select the date range for exporting candidate data (leave blank for all).</p>
            <div className="field"><label>From Date</label><input type="date" value={exportFrom} onChange={(e) => setExportFrom(e.target.value)} /></div>
            <div className="field"><label>To Date</label><input type="date" value={exportTo} onChange={(e) => setExportTo(e.target.value)} /></div>
            <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button className="btn" onClick={() => setExportOpen(false)}>Cancel</button>
              <button className="btn primary" style={{ width: 'auto' }} onClick={handleExport} disabled={exporting}>
                {exporting ? 'Exporting…' : 'Export'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
