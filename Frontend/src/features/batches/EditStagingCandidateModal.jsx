import { useState } from 'react';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';
import { isoToDMY } from '../../utils/datetime';

// Same editable-field set and "blank Aadhaar box means leave it alone" convention as
// CandidateErrorRow.jsx's inline edit form (Validate step) - this is the equivalent for the
// Review and Confirmation step, which has no spare row width for an inline form (its table
// already carries a Last Attempt/History column CandidateErrorRow's doesn't), so this is a
// modal instead of an inline row.
export default function EditStagingCandidateModal({ batch, candidate, onClose, onSaved }) {
  const [form, setForm] = useState({
    first_name: candidate.first_name || '',
    last_name: candidate.last_name || '',
    email: candidate.email || '',
    phone: candidate.phone || '',
    aadhaar_last4: '',
    date_of_birth: isoToDMY(candidate.date_of_birth),
    college_name: candidate.college_name || '',
    degree: candidate.degree || '',
    stream: candidate.stream || '',
    percentage: candidate.percentage ?? '',
    passing_out_year: candidate.passing_out_year ?? '',
    location: candidate.location || '',
  });
  const [saving, setSaving] = useState(false);

  function set(field, value) {
    setForm((f) => ({ ...f, [field]: value }));
  }

  async function handleSave() {
    setSaving(true);
    try {
      const payload = { ...form };
      // Blank means "leave it alone" - only 4 digits are ever stored, so the box starts empty
      // rather than prefilled, and sending an empty string would clear it instead.
      if (!payload.aadhaar_last4) delete payload.aadhaar_last4;
      const result = await batchApi.updateStagingCandidate(batch.batch_id, candidate.candidate_id, payload);
      toast.success('Candidate updated.');
      onSaved(result);
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 430 }}>
        <h4>Edit Candidate Details</h4>
        <p>Row {candidate.upload_row_number ?? candidate.candidate_id}</p>
        <div className="grid-2">
          <div className="field"><label>First Name</label><input value={form.first_name} onChange={(e) => set('first_name', e.target.value)} /></div>
          <div className="field"><label>Last Name</label><input value={form.last_name} onChange={(e) => set('last_name', e.target.value)} /></div>
        </div>
        <div className="field"><label>Email Address</label><input value={form.email} onChange={(e) => set('email', e.target.value)} /></div>
        <div className="grid-2">
          <div className="field"><label>Mobile</label><input value={form.phone} onChange={(e) => set('phone', e.target.value)} /></div>
          <div className="field">
            <label>
              Aadhaar Last 4 Digits{' '}
              <span style={{ color: 'var(--muted)', fontWeight: 400 }}>
                — currently {candidate.aadhaar_last4 || 'not set'}
              </span>
            </label>
            <input value={form.aadhaar_last4} placeholder="Leave blank to keep the current value"
                   onChange={(e) => set('aadhaar_last4', e.target.value)} />
          </div>
        </div>
        <div className="field">
          <label>Date of Birth</label>
          <input value={form.date_of_birth} placeholder="DD/MM/YYYY"
                 onChange={(e) => set('date_of_birth', e.target.value)} />
        </div>
        <div className="field"><label>College Name</label><input value={form.college_name} onChange={(e) => set('college_name', e.target.value)} /></div>
        <div className="grid-2">
          <div className="field"><label>Degree</label><input value={form.degree} onChange={(e) => set('degree', e.target.value)} /></div>
          <div className="field"><label>Stream</label><input value={form.stream} onChange={(e) => set('stream', e.target.value)} /></div>
        </div>
        <div className="grid-2">
          <div className="field"><label>Percentage</label><input type="number" value={form.percentage} onChange={(e) => set('percentage', e.target.value)} /></div>
          <div className="field"><label>Passing Out Year</label><input type="number" value={form.passing_out_year} onChange={(e) => set('passing_out_year', e.target.value)} /></div>
        </div>
        <div className="field"><label>Location</label><input value={form.location} onChange={(e) => set('location', e.target.value)} /></div>
        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="btn primary" onClick={handleSave} disabled={saving}>
            <ButtonSpinner loading={saving}>💾 Save</ButtonSpinner>
          </button>
        </div>
      </div>
    </div>
  );
}
