import { useRef, useState } from 'react';
import toast from 'react-hot-toast';
import * as candidateApi from '../../api/candidateApi';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';

// The surrounding wording is fixed server-side (email_templates.CERTIFICATION_TEMPLATE); the
// deadline and both course URLs are per-send values, so a different course can be assigned
// without a code change. These two defaults mirror the server's own
// DEFAULT_CERTIFICATION_COURSE_*_URL constants - if those change, change these too, or the
// prefilled value stops matching what an untouched send would actually use.
const DEFAULT_COURSE_1_URL = 'https://academy.uipath.com/courses/introduction-to-automation';
const DEFAULT_COURSE_2_URL =
  'https://academy.uipath.com/learning-plans/automation-developer-associate-training';

export default function CertificationModal({ candidateIds, onClose, onSent }) {
  const [deadline, setDeadline] = useState('');
  const [course1Url, setCourse1Url] = useState(DEFAULT_COURSE_1_URL);
  const [course2Url, setCourse2Url] = useState(DEFAULT_COURSE_2_URL);
  const [sending, setSending] = useState(false);
  const sendingRef = useRef(false);

  async function handleSend() {
    if (sendingRef.current) return;
    if (!deadline.trim()) {
      toast.error('Enter the completion deadline first.');
      return;
    }
    // Checked here as well as server-side so a typo is caught before it becomes a send to real
    // candidates - the server is still the authority and rejects the same thing.
    for (const [label, url] of [['first', course1Url], ['second', course2Url]]) {
      if (!url.trim()) {
        toast.error(`Enter the ${label} course link, or leave the default in place.`);
        return;
      }
      if (!url.trim().toLowerCase().startsWith('https://')) {
        toast.error(`The ${label} course link must be a full https:// link.`);
        return;
      }
    }
    sendingRef.current = true;
    setSending(true);
    try {
      const res = await candidateApi.sendCertificationEmail(candidateIds, {
        deadline: deadline.trim(),
        course1Url: course1Url.trim(),
        course2Url: course2Url.trim(),
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
          Sends the certification email to the {candidateIds.length} selected candidate(s). The
          wording is fixed — you set the deadline and the two course links.
        </p>

        <div className="field">
          <label htmlFor="cert_deadline">Completion Deadline</label>
          <input
            id="cert_deadline"
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
          <label htmlFor="cert_course_1">Course 1 Link</label>
          <input
            id="cert_course_1"
            value={course1Url}
            onChange={(e) => setCourse1Url(e.target.value)}
            placeholder="https://…"
            maxLength={500}
          />
          <div className="field-hint">
            Shown in the email under “Introduction to Automation Course | UiPath Academy”.
          </div>
        </div>

        <div className="field">
          <label htmlFor="cert_course_2">Course 2 Link</label>
          <input
            id="cert_course_2"
            value={course2Url}
            onChange={(e) => setCourse2Url(e.target.value)}
            placeholder="https://…"
            maxLength={500}
          />
          <div className="field-hint">
            Shown in the email under “Automation Developer Associate Training”. Both links are
            emailed to real candidates — check them before sending.
          </div>
        </div>

        <div className="field">
          <label>Email Preview</label>
          <div className="input-box filled"
               style={{ whiteSpace: 'pre-wrap', fontSize: 12, lineHeight: 1.6,
                        maxHeight: 260, overflowY: 'auto' }}>
{`Dear [Candidate Name],

Congratulations for clearing HR screening round! As part of the next step in the hiring process, we request you to complete the following certification requirements and share the proof within the given deadline.

Course Details (Mandatory):

1. Introduction to Automation Course | UiPath Academy
   ${course1Url || '<course 1 link>'}
   - Platform: UiPath Academy
   - Please share the PDF certificate/diploma after completion.

2. Automation Developer Associate Training
   ${course2Url || '<course 2 link>'}
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
