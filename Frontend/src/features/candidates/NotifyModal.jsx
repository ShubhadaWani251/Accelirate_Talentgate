import { useState } from 'react';
import toast from 'react-hot-toast';
import * as candidateApi from '../../api/candidateApi';
import { extractErrorMessage } from '../../utils/passwordSchema';

const NOTIFY_TEMPLATES = [
  { key: 'hold', label: '🕒 On Hold',
    text: 'Hi, thank you for completing the assessment. Your application is currently on hold pending further review — we will update you shortly.' },
  { key: 'cutoff', label: '📉 Cutoff Changed',
    text: 'Hi, please note the qualifying cutoff for your section has been revised. Your result is being re-evaluated against the updated cutoff.' },
  { key: 'shortlisted', label: '✅ Shortlisted',
    text: 'Congratulations! You have been shortlisted for the next round. Further details will follow by email shortly.' },
  { key: 'custom', label: '✍ Custom Message', text: '' },
];

export default function NotifyModal({ candidateIds, onClose, onSent }) {
  const [message, setMessage] = useState('');
  const [sending, setSending] = useState(false);

  async function handleSend() {
    if (!message.trim()) {
      toast.error('Write or pick a message first.');
      return;
    }
    setSending(true);
    try {
      const res = await candidateApi.notifyCandidates(candidateIds, 'Accelirate TalentGate - Update', message);
      toast.success(`Notified ${res.notified_count} candidate(s).`);
      onSent();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 440 }}>
        <h4>Notify Selected Candidates</h4>
        <p>Sends an email to every selected candidate. Pick a template, review or edit it, then send.</p>
        <div className="btn-row" style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 10 }}>
          {NOTIFY_TEMPLATES.map((t) => (
            <button key={t.key} className="btn small" onClick={() => setMessage(t.text)}>{t.label}</button>
          ))}
        </div>
        <div className="field">
          <label>Message (editable)</label>
          <textarea rows={4} value={message} onChange={(e) => setMessage(e.target.value)}
            placeholder="Select a template above, or write a custom message…" />
        </div>
        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" style={{ width: 'auto' }} onClick={handleSend} disabled={sending}>
            {sending ? 'Sending…' : '📧 Send Email'}
          </button>
        </div>
      </div>
    </div>
  );
}
