import { useState } from 'react';
import toast from 'react-hot-toast';
import * as candidateApi from '../../api/candidateApi';
import { extractErrorMessage } from '../../utils/passwordSchema';

// Deliberately excludes Aadhaar and Batch from the editable fields - the backend
// (CandidateUpdateSerializer) rejects them too, since changing either would silently invalidate
// the duplicate-check that already ran against this candidate's current values.
export default function EditCandidateModal({ candidate, onClose, onSaved }) {
  const [form, setForm] = useState({
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
  const [saving, setSaving] = useState(false);
  const [resendConfirming, setResendConfirming] = useState(false);

  function set(field, value) {
    setForm({ ...form, [field]: value });
  }

  async function handleSave() {
    setSaving(true);
    try {
      await candidateApi.updateCandidate(candidate.candidate_id, form);
      toast.success('Candidate updated.');
      onSaved();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function handleResendInvite() {
    setResendConfirming(false);
    try {
      const res = await candidateApi.resendInvite(candidate.candidate_id);
      toast.success(res.detail);
      onSaved();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    }
  }

  return (
    <>
      <div className="modal-overlay" onClick={onClose}>
        <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 430 }}>
          <h4>Edit Candidate Details</h4>
          <p>Update candidate information or resend the assessment invitation.</p>
          <div className="grid-2">
            <div className="field"><label>First Name</label><input value={form.first_name} onChange={(e) => set('first_name', e.target.value)} /></div>
            <div className="field"><label>Last Name</label><input value={form.last_name} onChange={(e) => set('last_name', e.target.value)} /></div>
          </div>
          <div className="field"><label>Email Address</label><input value={form.email} onChange={(e) => set('email', e.target.value)} /></div>
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
            <button className="btn" onClick={onClose}>Cancel</button>
            <button className="btn" onClick={() => setResendConfirming(true)}>📧 Send Invite Again</button>
            <button className="btn primary" style={{ width: 'auto' }} onClick={handleSave} disabled={saving}>
              {saving ? 'Saving…' : '💾 Save'}
            </button>
          </div>
        </div>
      </div>

      {resendConfirming && (
        <div className="modal-overlay" onClick={() => setResendConfirming(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 360 }}>
            <h4>Send Invite Again?</h4>
            <p>This will re-send the assessment invite link to {candidate.email}. Continue?</p>
            <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button className="btn" onClick={() => setResendConfirming(false)}>Cancel</button>
              <button className="btn primary" style={{ width: 'auto' }} onClick={handleResendInvite}>Confirm &amp; Send</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
