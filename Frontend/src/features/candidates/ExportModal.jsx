import { useState } from 'react';
import toast from 'react-hot-toast';
import * as candidateApi from '../../api/candidateApi';
import { extractErrorMessage } from '../../utils/passwordSchema';

// What each filter key is called on screen, so the modal can say which ones it is about to
// honour rather than claiming "your filters" and leaving the reader to trust it. Keys not
// listed here are the per-section score ranges, which are data (an admin can add a section),
// so they are labelled from the key itself below rather than enumerated.
const FILTER_LABELS = {
  name: 'Name',
  email: 'Email',
  aadhaar: 'Aadhaar',
  batch_id: 'Batch',
  result: 'Result',
  batch_status: 'Batch status',
  status: 'Exam status',
};

// A `<section_key>_min` / `_max` pair is one filter to a reader, not two. Collapsed to the stem
// so "Overall score" appears once whether one bound is set or both.
function describeFilters(filters) {
  const names = new Set();
  Object.entries(filters || {}).forEach(([key, value]) => {
    if (value === '' || value === null || value === undefined) return;
    if (FILTER_LABELS[key]) { names.add(FILTER_LABELS[key]); return; }
    const stem = key.replace(/_(min|max)$/, '');
    if (stem === key) return;             // unknown key, not a range - nothing sensible to call it
    names.add(stem === 'score'
      ? 'Overall score'
      : `${stem.charAt(0).toUpperCase()}${stem.slice(1)} score`);
  });
  return Array.from(names);
}

// batchId scopes the export to one batch (Batch Details). `filters` carries the All Candidates
// filter state, so Export there means "this list as a spreadsheet". Both omitted on the
// Dashboard and the sidebar's Export action, where it genuinely does mean every candidate.
export default function ExportModal({ onClose, batchId, filters }) {
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [exporting, setExporting] = useState(false);

  const applied = describeFilters(filters);

  async function handleExport() {
    setExporting(true);
    try {
      await candidateApi.exportCandidates({ from: from || undefined, to: to || undefined, batchId, filters });
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
        {/* Named rather than counted: "3 filters applied" still leaves the reader opening the
            spreadsheet to find out which rows they got. */}
        {applied.length > 0 && (
          <p className="export-scope">
            Exporting only the candidates currently listed — filtered by{' '}
            <strong>{applied.join(', ')}</strong>.
          </p>
        )}
        <div className="field"><label>From Date</label><input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></div>
        <div className="field"><label>To Date</label><input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></div>
        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={handleExport} disabled={exporting}>
            {exporting ? 'Exporting…' : 'Export'}
          </button>
        </div>
      </div>
    </div>
  );
}
