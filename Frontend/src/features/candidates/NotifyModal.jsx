import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import * as candidateApi from '../../api/candidateApi';
import { extractErrorMessage } from '../../utils/passwordSchema';

// Icons are presentation-only; the labels and copy come from the backend template registry so
// the approved wording lives in exactly one place.
const TEMPLATE_ICONS = {
  hold: '🕒', cutoff: '📉', shortlisted: '✅', fail: '❌',
  review: '🔍', technical_issue: '🛠',
};

export default function NotifyModal({ candidateIds, onClose, onSent }) {
  const [templates, setTemplates] = useState([]);
  const [activeKey, setActiveKey] = useState(null);
  const [message, setMessage] = useState('');
  const [edited, setEdited] = useState(false);
  const [sending, setSending] = useState(false);

  useEffect(() => {
    candidateApi.listNotificationTemplates()
      .then(setTemplates)
      .catch((err) => toast.error(extractErrorMessage(err)));
  }, []);

  function pickTemplate(template) {
    setActiveKey(template.key);
    // {name} is substituted per recipient server-side - show it as a readable placeholder.
    setMessage(template.body.replaceAll('{name}', '[Candidate Name]'));
    setEdited(false);
  }

  function pickCustom() {
    setActiveKey(null);
    setMessage('');
    setEdited(true);
  }

  async function handleSend() {
    if (candidateIds.length === 0) {
      toast.error('Select at least one candidate first.');
      return;
    }
    if (!activeKey && !message.trim()) {
      toast.error('Pick a template or write a message first.');
      return;
    }
    setSending(true);
    try {
      // An untouched template is sent from the approved copy server-side (personalised per
      // candidate); only an edited body is sent up as an override.
      const res = await candidateApi.notifyCandidates(candidateIds, {
        template: activeKey || undefined,
        message: edited ? message : undefined,
      });
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
      <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 460 }}>
        <h4>Notify Selected Candidates</h4>
        <p>
          Sends an email to the {candidateIds.length} checked candidate(s) — nobody else. Pick a
          template, review or edit it, then send.
        </p>

        <div className="card" style={{ background: '#f4f6f8', marginBottom: 10 }}>
          <div className="box-label">Choose a Template</div>
          <div className="btn-row" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {templates.map((t) => (
              <button
                key={t.key}
                className={`btn small ${activeKey === t.key ? 'primary' : ''}`}
                style={activeKey === t.key ? { width: 'auto' } : undefined}
                onClick={() => pickTemplate(t)}
              >
                {TEMPLATE_ICONS[t.key] || '✉'} {t.label}
              </button>
            ))}
            <button className={`btn small ${activeKey === null && edited ? 'primary' : ''}`}
              style={activeKey === null && edited ? { width: 'auto' } : undefined}
              onClick={pickCustom}>
              ✍ Custom Message
            </button>
          </div>
        </div>

        <div className="field">
          <label>Message Preview (editable)</label>
          <textarea
            rows={7}
            value={message}
            onChange={(e) => { setMessage(e.target.value); setEdited(true); }}
            placeholder="Select a template above, or write a custom message…"
          />
          {activeKey && !edited && (
            <div className="field-hint">
              Approved template — sent as-is, with each candidate&apos;s own name filled in.
            </div>
          )}
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
