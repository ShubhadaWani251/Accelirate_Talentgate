import { useRef, useState } from 'react';
import toast from 'react-hot-toast';
import * as candidateApi from '../../api/candidateApi';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';

// The email body is fixed server-side (email_templates.CERTIFICATION_TEMPLATE), including both
// UiPath course links - they're part of the approved copy, not something a TA pastes in, so the
// wrong course can never be sent. The only per-send value is the completion deadline.
//
// The preview below mirrors that copy. It is a copy, so if the approved wording changes in
// email_templates.py this text needs the same edit; the email itself is always rendered from
// the server-side template, never from this string.
export default function CertificationModal({ candidateIds, onClose, onSent }) {
  const [deadline, setDeadline] = useState('');
  const [sending, setSending] = useState(false);
  const sendingRef = useRef(false);

  async function handleSend() {
    if (sendingRef.current) return;
    if (!deadline.trim()) {
      toast.error('Enter the completion deadline first.');
      return;
    }
    sendingRef.current = true;
    setSending(true);
    try {
      const res = await candidateApi.sendCertificationEmail(candidateIds, {
        deadline: deadline.trim(),
      });
      toast.success(`Certification email sent to ${res.notified_count} candidate(s).`);
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
      <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 560 }}>
        <h4>Send Certification Course Email</h4>
        <p>
          Sends the approved certification email to the {candidateIds.length} selected
          candidate(s). The course links and wording are fixed — you only set the deadline.
        </p>

        <div className="field">
          <label>Completion Deadline</label>
          <input
            value={deadline}
            onChange={(e) => setDeadline(e.target.value)}
            placeholder="e.g. 5 March 2026, or Friday 5 March (EOD)"
            maxLength={80}
          />
          <div className="field-hint">
            Written into the email exactly as typed, so use whatever wording the candidates
            should see.
          </div>
        </div>

        <div className="field">
          <label>Email Preview (fixed template)</label>
          <div className="input-box filled"
               style={{ whiteSpace: 'pre-wrap', fontSize: 12, lineHeight: 1.6,
                        maxHeight: 260, overflowY: 'auto' }}>
{`Dear [Candidate Name],

Congratulations for clearing HR screening round! As part of the next step in the hiring process, we request you to complete the following certification requirements and share the proof within the given deadline.

Course Details (Mandatory):

1. Introduction to Automation Course | UiPath Academy
   https://academy.uipath.com/courses/introduction-to-automation
   - Platform: UiPath Academy
   - Please share the PDF certificate/diploma after completion.

2. Automation Developer Associate Training
   https://academy.uipath.com/learning-plans/automation-developer-associate-training
   - Platform: UiPath Academy
   - Learning Plan: Automation Developer Associate Training
   - Complete the first 11 modules
   - Please share screenshots of the completed modules as proof.

Deadline: ${deadline || '<deadline>'}

Kindly ensure that all required documents/screenshots are shared before the deadline, as this is an important part of the evaluation process.

If you have any questions or face any issues while accessing the courses, feel free to reach out.

Regards,
Talent Acquisition Team
Accelirate Softech Pvt. Ltd.`}
          </div>
        </div>

        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={handleSend} disabled={sending}>
            <ButtonSpinner loading={sending}>🎓 Send Certification Email</ButtonSpinner>
          </button>
        </div>
      </div>
    </div>
  );
}
