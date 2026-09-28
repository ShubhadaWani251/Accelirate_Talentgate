import { useEffect, useRef, useState } from 'react';
import toast from 'react-hot-toast';
import * as candidateApi from '../../api/candidateApi';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';

// What a body may substitute. Mirrors email_templates.CERTIFICATION_PLACEHOLDERS, and the server
// re-checks every send - this copy only exists so a typo is caught before it becomes an email to
// real candidates.
const PLACEHOLDERS = ['name', 'deadline', 'course_1_url', 'course_2_url'];

// The preview substitutes the same way the server will, so what is on screen is what a candidate
// receives - with the TA's own values where they have typed them, and a visible marker where
// they have not.
function renderPreview(body, { deadline, course1Url, course2Url }) {
  const values = {
    name: '[Candidate Name]',
    deadline: deadline || '<deadline>',
    course_1_url: course1Url || '<course 1 link>',
    course_2_url: course2Url || '<course 2 link>',
  };
  // Doubled braces are literals, exactly as str.format reads them, so a body containing {{ }}
  // previews the way it will send.
  return body
    .replace(/\{\{|\}\}|\{(\w+)\}/g, (match, name) => {
      if (match === '{{') return '{';
      if (match === '}}') return '}';
      return name in values ? values[name] : match;
    });
}

// Surfaces the two ways an edited body can fail to render, before the send rather than after.
function bodyError(body) {
  if (!body.trim()) return 'The email body cannot be empty.';
  const stripped = body.replace(/\{\{|\}\}/g, '');
  const unknown = [...stripped.matchAll(/\{(\w*)\}/g)]
    .map((m) => m[1])
    .find((name) => !PLACEHOLDERS.includes(name));
  if (unknown !== undefined) {
    return `{${unknown}} is not a placeholder this email understands. Available: `
      + PLACEHOLDERS.map((p) => `{${p}}`).join(', ');
  }
  if (/\{(?![\w]*\})/.test(stripped) || /(?<!\{[\w]*)\}/.test(stripped)) {
    return 'A brace in the body is unbalanced. Use {{ and }} for a literal { or }.';
  }
  return null;
}

export default function CertificationModal({ candidateIds, onClose, onSent }) {
  const [deadline, setDeadline] = useState('');
  const [course1Url, setCourse1Url] = useState('');
  const [course2Url, setCourse2Url] = useState('');
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [saveAsDefault, setSaveAsDefault] = useState(false);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const sendingRef = useRef(false);

  // Loaded from the server rather than held as constants here. The wording is editable and can
  // have been changed by someone else since this bundle was built, so the only copy worth
  // editing is the one currently in force.
  useEffect(() => {
    candidateApi.getCertificationTemplate()
      .then((data) => {
        setSubject(data.subject);
        setBody(data.body);
        setCourse1Url(data.course_1_url);
        setCourse2Url(data.course_2_url);
      })
      .catch((err) => toast.error(extractErrorMessage(err)))
      .finally(() => setLoading(false));
  }, []);

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
    if (!subject.trim()) {
      toast.error('Enter the email subject.');
      return;
    }
    const invalid = bodyError(body);
    if (invalid) {
      toast.error(invalid);
      return;
    }
    sendingRef.current = true;
    setSending(true);
    try {
      const res = await candidateApi.sendCertificationEmail(candidateIds, {
        deadline: deadline.trim(),
        course1Url: course1Url.trim(),
        course2Url: course2Url.trim(),
        subject: subject.trim(),
        body,
        saveAsDefault,
      });
      toast.success(
        `Certification email sent to ${res.notified_count} candidate(s).`
        + (saveAsDefault ? ' This wording is now the default.' : ''),
      );
      onSent();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      sendingRef.current = false;
      setSending(false);
    }
  }

  const invalidBody = loading ? null : bodyError(body);

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 620 }}>
        <h4>Send Certification Course Email</h4>
        <p>
          Sends the certification email to the {candidateIds.length} selected candidate(s). Every
          part of it can be edited — set the deadline and links, and change the wording if it
          needs to.
        </p>

        {loading ? (
          <div style={{ fontSize: 12.5, color: 'var(--muted)' }}>Loading the current wording…</div>
        ) : (
          <>
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
                Both links are emailed to real candidates — check them before sending.
              </div>
            </div>

            <div className="field">
              <label htmlFor="cert_subject">Subject</label>
              <input
                id="cert_subject"
                value={subject}
                onChange={(e) => setSubject(e.target.value)}
                maxLength={200}
              />
            </div>

            <div className="field">
              <label htmlFor="cert_body">Email Body</label>
              <textarea
                id="cert_body"
                className={invalidBody ? 'has-error' : ''}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                rows={12}
                style={{ fontFamily: 'inherit', fontSize: 12.5, lineHeight: 1.6,
                         whiteSpace: 'pre-wrap' }}
              />
              {invalidBody ? (
                <div className="field-error">{invalidBody}</div>
              ) : (
                <div className="field-hint">
                  {PLACEHOLDERS.map((p) => `{${p}}`).join(', ')} are filled in per candidate.
                  Write <code>{'{{'}</code> for a literal brace.
                </div>
              )}
            </div>

            {/* Off by default: a one-off tweak for a single send should not silently rewrite the
                wording every other TA starts from. Ticking it is the deliberate act of changing
                the template. */}
            <div className="field">
              <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13 }}>
                <input
                  type="checkbox"
                  checked={saveAsDefault}
                  onChange={(e) => setSaveAsDefault(e.target.checked)}
                />
                Save this wording as the default for future sends
              </label>
              <div className="field-hint">
                Leave unticked to use these changes for this send only.
              </div>
            </div>

            <div className="field">
              <label>Preview — what a candidate receives</label>
              <div className="input-box filled"
                   style={{ whiteSpace: 'pre-wrap', fontSize: 12, lineHeight: 1.6,
                            maxHeight: 220, overflowY: 'auto' }}>
                {renderPreview(body, { deadline, course1Url, course2Url })}
              </div>
            </div>
          </>
        )}

        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={handleSend}
                  disabled={sending || loading || Boolean(invalidBody)}>
            <ButtonSpinner loading={sending}>🎓 Send Certification Email</ButtonSpinner>
          </button>
        </div>
      </div>
    </div>
  );
}
