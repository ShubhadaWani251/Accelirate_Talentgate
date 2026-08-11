import { useState } from 'react';
import toast from 'react-hot-toast';
import * as candidateApi from '../../api/candidateApi';
import { extractErrorMessage } from '../../utils/passwordSchema';

// batchId scopes the export to one batch (Batch Details); omitted on All Candidates / Dashboard,
// where it exports everything in the given date range.
export default function ExportModal({ onClose, batchId }) {
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [exporting, setExporting] = useState(false);

  async function handleExport() {
    setExporting(true);
    try {
      await candidateApi.exportCandidates({ from: from || undefined, to: to || undefined, batchId });
      onClose();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setExporting(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <h4>Export Candidates</h4>
        <p>Select the date range for exporting candidate data (leave blank for all).</p>
        <div className="field"><label>From Date</label><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></div>
        <div className="field"><label>To Date</label><input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></div>
        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" style={{ width: 'auto' }} onClick={handleExport} disabled={exporting}>
            {exporting ? 'Exporting…' : 'Export'}
          </button>
        </div>
      </div>
    </div>
  );
}
