import { useRef, useState } from 'react';
import toast from 'react-hot-toast';
import * as candidateApi from '../../api/candidateApi';
import { extractErrorMessage } from '../../utils/passwordSchema';

// The email body is fixed server-side (email_templates.CERTIFICATION_TEMPLATE) - this modal
// only collects the two links, so the approved wording can't drift from one send to the next.
// What's shown below is a read-only preview of that copy with the links dropped in.
export default function CertificationModal({ candidateIds, onClose, onSent }) {
  const [linkOne, setLinkOne] = useState('');
  const [linkTwo, setLinkTwo] = useState('');
  const [sending, setSending] = useState(false);
  const sendingRef = useRef(false);

  async function handleSend() {
    if (sendingRef.current) return;
    if (!linkOne.trim() || !linkTwo.trim()) {
      toast.error('Paste both certification links first.');
      return;
    }
    sendingRef.current = true;
    setSending(true);
    try {
      const res = await candidateApi.sendCertificationLinks(candidateIds, {
        linkOne: linkOne.trim(), linkTwo: linkTwo.trim(),
      });
      toast.success(`Certification links sent to ${res.notified_count} candidate(s).`);
      onSent();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 480 }}>
        <h4>Send Certification Link</h4>
        <p>
          Sends the approved certification email to the {candidateIds.length} selected
          candidate(s). The wording is fixed — just paste the two links below.
        </p>

        <div className="field">
          <label>Certification Link 1</label>
          <input value={linkOne} onChange={(e) => setLinkOne(e.target.value)}
            placeholder="https://…" />
        </div>
        <div className="field">
          <label>Certification Link 2</label>
          <input value={linkTwo} onChange={(e) => setLinkTwo(e.target.value)}
            placeholder="https://…" />
        </div>

        <div className="field">
          <label>Email Preview (fixed template)</label>
          <div className="input-box filled" style={{ whiteSpace: 'pre-wrap', fontSize: 12, lineHeight: 1.6 }}>
{`Hi <candidate name>,

Congratulations on completing your assessment. Please use the links below to complete your certification.

Certification Link 1:
${linkOne || '<link 1>'}

Certification Link 2:
${linkTwo || '<link 2>'}

Please complete both steps at the earliest. If either link does not open, reply to this email and we will resend it.

Regards,
Talent Acquisition Team
Accelirate`}
          </div>
        </div>

        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" style={{ width: 'auto' }} onClick={handleSend} disabled={sending}>
            {sending ? 'Sending…' : '🎓 Send Certification Link'}
          </button>
        </div>
      </div>
    </div>
  );
}
