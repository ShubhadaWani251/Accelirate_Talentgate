import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import * as candidateApi from '../../api/candidateApi';
import ServerErrorPage from '../../components/error/ServerErrorPage';
import NotFoundPage from '../../components/error/NotFoundPage';
import { isResourceMissing } from '../../utils/apiError';
import {
  Skeleton, SkeletonCard, SkeletonPage, SkeletonTable,
} from '../../components/loading/Skeleton';
import { ButtonSpinner } from '../../components/loading/Spinner';
import { formatDateTime, fromDatetimeLocalValue, toDatetimeLocalValue } from '../../utils/datetime';
import { extractErrorMessage } from '../../utils/passwordSchema';

const RESULT_PILL = { pending: 'gray', pass: 'green', fail: 'red' };

export default function CandidateDetail() {
  const { id } = useParams();
  const [candidate, setCandidate] = useState(null);
  const [loading, setLoading] = useState(true);
  // null | 'notfound' | 'server' - which error page (if any) replaces this page.
  const [loadError, setLoadError] = useState(null);
  const [sending, setSending] = useState(false);
  const [downloadingZip, setDownloadingZip] = useState(false);
  const [inviteConfirmOpen, setInviteConfirmOpen] = useState(false);
  // Seeded from the batch's CURRENT window each time the dialog opens (not on load), so a
  // resend days later doesn't offer a stale value from when the page first rendered.
  const [linkValidFrom, setLinkValidFrom] = useState('');
  const [linkValidUntil, setLinkValidUntil] = useState('');

  function openInviteConfirm() {
    setLinkValidFrom(toDatetimeLocalValue(candidate.link_valid_from));
    setLinkValidUntil(toDatetimeLocalValue(candidate.link_valid_until));
    setInviteConfirmOpen(true);
  }

  async function refresh() {
    setLoading(true);
    try {
      setCandidate(await candidateApi.getCandidate(id));
      setLoadError(null);
    } catch (err) {
      toast.error(extractErrorMessage(err));
      // Otherwise candidate stays null and the page shows "Loading…" permanently. The KIND of
      // failure decides which page is shown: a missing candidate is a 404, not a server fault.
      setLoadError(isResourceMissing(err) ? 'notfound' : 'server');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function handleSendInvite() {
    if (!linkValidFrom || !linkValidUntil) {
      toast.error('Both Link Valid From and Link Valid Until are required.');
      return;
    }
    if (linkValidUntil <= linkValidFrom) {
      toast.error('Link Valid Until must be after Link Valid From.');
      return;
    }
    setSending(true);
    try {
      // Gives THIS invitation its own window rather than touching the batch's (which is
      // locked once the batch leaves Draft - see CandidateResendInviteView/create_single_
      // reinvite) - so this only ever affects this one candidate's new link.
      const res = await candidateApi.resendInvite(id, {
        link_valid_from: fromDatetimeLocalValue(linkValidFrom),
        link_valid_until: fromDatetimeLocalValue(linkValidUntil),
      });
      toast.success(res.detail);
      setInviteConfirmOpen(false);
      refresh();
    } catch (err) {
      toast.error(extractErrorMessage(err, ['link_valid_from', 'link_valid_until']));
    } finally {
      setSending(false);
    }
  }

  async function handleDownloadZip() {
    setDownloadingZip(true);
    try {
      await candidateApi.downloadEvidenceZip(id);
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setDownloadingZip(false);
    }
  }

  if (loadError === 'notfound') return <NotFoundPage standalone={false} />;
  if (loadError) return <ServerErrorPage onRetry={refresh} />;

  if (loading || !candidate) {
    return (
      <div className="page-wide">
        <SkeletonPage label="Loading candidate…">
          {/* Mirrors the real layout below: details grid, section-result table, evidence cards. */}
          <SkeletonCard lines={4} style={{ marginBottom: 20 }} />
          <div className="card" style={{ marginBottom: 20 }}>
            <Skeleton width="34%" height={11} style={{ marginBottom: 14 }} />
            <SkeletonTable rows={4} columns={4} label="Loading section results…" />
          </div>
          <div className="grid-3">
            <SkeletonCard lines={2} />
            <SkeletonCard lines={2} />
            <SkeletonCard lines={2} />
          </div>
        </SkeletonPage>
      </div>
    );
  }

  const hasAnyEvidence = Object.values(candidate.evidence).some(Boolean);

  return (
    <div className="page-wide">
      <h3>
        Candidate Details — {candidate.full_name}{' '}
        <span className={`pill ${RESULT_PILL[candidate.result] || 'gray'}`}>{candidate.result_display}</span>
      </h3>

      <div className="grid-2">
        <div className="card">
          <div className="box-label">Personal Info</div>
          <div className="field"><label>Name</label><div>{candidate.full_name}</div></div>
          <div className="field"><label>Email</label><div>{candidate.email}</div></div>
          <div className="field"><label>Aadhaar Last 4 Digits</label><div>{candidate.aadhaar_last4 || '—'}</div></div>
          {/* Shown here as well as in the list, with the full failure reason - this is where
              someone lands when investigating why a candidate never got their link. */}
          <div className="field">
            <label>Invitation Email</label>
            <div>
              {candidate.email_status_display || 'Not invited'}
              {candidate.email_sent_at && (
                <span style={{ color: 'var(--muted)' }}>
                  {' '}— {new Date(candidate.email_sent_at).toLocaleString()}
                </span>
              )}
            </div>
            {candidate.email_status === 'failed' && (
              <div className="field-error" style={{ whiteSpace: 'normal' }}>
                {candidate.email_error || 'The email service reported a failure.'}
                {candidate.email_last_attempt_at && (
                  <> (last tried {new Date(candidate.email_last_attempt_at).toLocaleString()})</>
                )}
              </div>
            )}
          </div>
          <div className="field"><label>College</label><div>{candidate.college_name || '—'}</div></div>
          <div className="field"><label>Degree</label><div>{candidate.degree || '—'}</div></div>
          <div className="field"><label>Stream</label><div>{candidate.stream || '—'}</div></div>
          <div className="field"><label>Percentage</label><div>{candidate.percentage != null ? `${candidate.percentage}%` : '—'}</div></div>
          <div className="field"><label>Passing Out Year</label><div>{candidate.passing_out_year || '—'}</div></div>
          <div className="field"><label>Location</label><div>{candidate.location || '—'}</div></div>
          <div className="field"><label>Phone</label><div>{candidate.phone || '—'}</div></div>
          <div className="field"><label>Batch</label><div>{candidate.batch_name}</div></div>
        </div>

        <div className="card">
          <div className="box-label">Section-wise Result</div>
          {/* .table-scroll so the table can't widen the page on a phone. */}
          <div className="table-scroll">
          <table className="data-table">
            <thead><tr><th>Section</th><th>Score</th><th>Cutoff</th><th></th></tr></thead>
            <tbody>
              {candidate.section_results.map((row) => (
                <tr key={row.section}>
                  <td>{row.section}</td>
                  {/* Denominator comes from the batch's own per-section count - it used to be
                      hardcoded to /10, which read wrong for any other configuration. */}
                  <td>{row.score != null ? `${row.score}/${row.total}` : `—/${row.total}`}</td>
                  <td>{row.cutoff}%</td>
                  <td>
                    {row.cleared == null ? (
                      <span className="pill gray">Not Attempted</span>
                    ) : (
                      <span className={`pill ${row.cleared ? 'green' : 'red'}`}>
                        {row.cleared ? 'Cleared' : 'Not Cleared'}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          <div style={{ fontSize: 12.5, marginTop: 8 }}>
            <b>
              {/* total_correct is the mark COUNT; overall_score is a PERCENTAGE. Rendering the
                  percentage over the question count is what made 2-of-40 read as "5/40". */}
              Overall: {candidate.total_correct != null
                ? `${candidate.total_correct}/${candidate.overall_total} (${candidate.overall_score}%)`
                : `—/${candidate.overall_total}`}{' '}
              · <span className={`pill ${RESULT_PILL[candidate.result] || 'gray'}`}>{candidate.result_display}</span>
            </b>
          </div>
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="box-label">Identity Verification &amp; Proctoring</div>
        {/* Three tiles, three columns - grid-4 left a dead fourth column and squeezed them. */}
        <div className="grid-3">
          <div>
            <div style={{ border: '1px dashed var(--line-soft)', borderRadius: 8, textAlign: 'center', padding: 20 }}>
              🪪<br /><span style={{ fontSize: 11, color: 'var(--muted)' }}>Aadhaar</span>
            </div>
            {candidate.evidence.aadhaar_capture_url ? (
              <div style={{ display: 'flex', gap: 12, justifyContent: 'center', marginTop: 4 }}>
                <a className="link-text" href={candidate.evidence.aadhaar_capture_url} target="_blank" rel="noopener noreferrer">View Full Image</a>
                <a className="link-text" href={candidate.evidence.aadhaar_capture_download_url} download>⬇ Download</a>
              </div>
            ) : (
              <div style={{ textAlign: 'center', fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>Not yet captured</div>
            )}
          </div>
          <div>
            <div style={{ border: '1px dashed var(--line-soft)', borderRadius: 8, textAlign: 'center', padding: 20 }}>
              🙂<br /><span style={{ fontSize: 11, color: 'var(--muted)' }}>Live face photo</span>
            </div>
            {candidate.evidence.face_photo_url ? (
              <div style={{ display: 'flex', gap: 12, justifyContent: 'center', marginTop: 4 }}>
                <a className="link-text" href={candidate.evidence.face_photo_url} target="_blank" rel="noopener noreferrer">View Full Image</a>
                <a className="link-text" href={candidate.evidence.face_photo_download_url} download>⬇ Download</a>
              </div>
            ) : (
              <div style={{ textAlign: 'center', fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>Not yet captured</div>
            )}
          </div>
          <div>
            <div style={{ border: '1px dashed var(--line-soft)', borderRadius: 8, textAlign: 'center', padding: 20 }}>
              🎥<br /><span style={{ fontSize: 11, color: 'var(--muted)' }}>Session recording</span>
            </div>
            {candidate.evidence.session_recording_url ? (
              <div style={{ display: 'flex', gap: 12, justifyContent: 'center', marginTop: 4 }}>
                <a className="link-text" href={candidate.evidence.session_recording_url} target="_blank" rel="noopener noreferrer">▶ Play Recording</a>
                <a className="link-text" href={candidate.evidence.session_recording_download_url} download>⬇ Download</a>
              </div>
            ) : (
              <div style={{ textAlign: 'center', fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>Not yet recorded</div>
            )}
          </div>
        </div>
        {hasAnyEvidence && (
          <div className="btn-row no-print" style={{ marginTop: 12 }}>
            <button className="btn" onClick={handleDownloadZip} disabled={downloadingZip}>
              <ButtonSpinner loading={downloadingZip}>⬇ Download All Evidence (ZIP)</ButtonSpinner>
            </button>
          </div>
        )}
        <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 10 }}>
          Populated once the candidate completes their proctored assessment.
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="box-label">Process / Status History</div>
        <div className="table-scroll">
          <table className="data-table">
            <thead><tr><th>Date/Time</th><th>Event</th><th>Details</th><th>Batch</th></tr></thead>
            <tbody>
              {candidate.timeline.map((event, i) => (
                <tr key={i}>
                  <td>{formatDateTime(event.timestamp)}</td>
                  <td>{event.event}</td>
                  <td>{event.details || '—'}</td>
                  <td>{event.batch_name}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {candidate.other_batches?.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="box-label">Other Batches</div>
          {/* Same person (matched by Aadhaar + name), appearing in other batches too - see
              services/candidate_profile.py. Each is still its own record with its own result;
              this is just a pointer to the others, not a merge. */}
          <div className="table-scroll">
            <table className="data-table">
              <thead><tr><th>Batch</th><th>Date</th><th>Result</th><th></th></tr></thead>
              <tbody>
                {candidate.other_batches.map((row) => (
                  <tr key={row.candidate_id}>
                    <td>{row.batch_name}</td>
                    <td>{formatDateTime(row.created_at)}</td>
                    <td><span className={`pill ${RESULT_PILL[row.result] || 'gray'}`}>{row.result_display}</span></td>
                    <td><Link className="link-text" to={`/candidates/${row.candidate_id}`}>View</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="btn-row no-print" style={{ display: 'flex', gap: 10, marginTop: 16 }}>
        <button className="btn primary" onClick={openInviteConfirm} disabled={sending}>
          <ButtonSpinner loading={sending}>Send Invite Link</ButtonSpinner>
        </button>
        <button className="btn" onClick={() => window.print()}>🖨 Export Candidate Details (PDF)</button>
      </div>

      {inviteConfirmOpen && (
        <div className="modal-overlay">
          <div className="modal-box">
            <h4>Send a new invite link?</h4>
            <p>
              {candidate.full_name} will be emailed a <b>new</b> assessment link. Any link they
              were sent previously will no longer be the one they should use. If they have
              already submitted or been terminated, they cannot retake the assessment.
            </p>
            {/* This window belongs to the whole batch ({candidate.batch_name}), not just this
                candidate - changing it here affects every other candidate in it too, same as
                setting it does from the upload wizard. */}
            <div className="grid-2">
              <div className="field">
                <label htmlFor="resend_link_valid_from">Link Valid From</label>
                <input id="resend_link_valid_from" type="datetime-local" value={linkValidFrom}
                       onChange={(e) => setLinkValidFrom(e.target.value)} />
              </div>
              <div className="field">
                <label htmlFor="resend_link_valid_until">Link Valid Until</label>
                <input id="resend_link_valid_until" type="datetime-local" value={linkValidUntil}
                       onChange={(e) => setLinkValidUntil(e.target.value)} />
              </div>
            </div>
            <div className="btn-row">
              <button className="btn" type="button" onClick={() => setInviteConfirmOpen(false)}>
                Cancel
              </button>
              <button className="btn primary" type="button" disabled={sending}
                      onClick={handleSendInvite}>
                <ButtonSpinner loading={sending}>Send Invite Link</ButtonSpinner>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
