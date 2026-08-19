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
    setSaving(true);
    let saved = false;
    try {
      // Save the edits FIRST, then send. The invite is addressed server-side from the stored
      // candidate record, so re-sending without saving would mail the old address and silently
      // discard whatever the TA just typed in this form.
      await candidateApi.updateCandidate(candidate.candidate_id, form);
      saved = true;
      const res = await candidateApi.resendInvite(candidate.candidate_id);
      toast.success(`Changes saved. ${res.detail}`);
      onSaved();
    } catch (err) {
      const message = extractErrorMessage(err);
      // Which half failed matters: if the save failed nothing was sent and the edits are still
      // unsaved, but if the save succeeded the edits ARE persisted and only the email failed -
      // one generic error would leave the TA unsure whether to re-enter everything.
      if (saved) {
        toast.error(`Changes were saved, but the invite could not be sent: ${message}`);
        onSaved();
      } else {
        toast.error(`Changes not saved, invite not sent: ${message}`);
      }
    } finally {
      setSaving(false);
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
            <button className="btn primary" onClick={handleSave} disabled={saving}>
              {saving ? 'Saving…' : '💾 Save'}
            </button>
          </div>
        </div>
      </div>

      {resendConfirming && (
        <div className="modal-overlay" onClick={() => setResendConfirming(false)}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 360 }}>
            <h4>Send Invite Again?</h4>
            {/* form.email, NOT candidate.email: the edits are saved before sending, so the invite
                goes to the address currently in the form. Showing the original prop here named a
                different address than the one actually about to be emailed. */}
            <p>
              Your changes will be saved, then the assessment invite link will be sent to{' '}
              <b>{form.email}</b>.
              {form.email !== candidate.email && (
                <> This is different from the previously saved address ({candidate.email}).</>
              )}{' '}
              Continue?
            </p>
            <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button className="btn" onClick={() => setResendConfirming(false)}>Cancel</button>
              <button className="btn primary" onClick={handleResendInvite}>Confirm &amp; Send</button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}
