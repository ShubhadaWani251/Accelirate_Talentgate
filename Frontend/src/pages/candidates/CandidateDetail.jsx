import { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import * as candidateApi from '../../api/candidateApi';
import { formatDateTime } from '../../utils/datetime';
import { extractErrorMessage } from '../../utils/passwordSchema';

const RESULT_PILL = { pending: 'gray', pass: 'green', fail: 'red' };

export default function CandidateDetail() {
  const { id } = useParams();
  const [candidate, setCandidate] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [downloadingZip, setDownloadingZip] = useState(false);

  async function refresh() {
    setLoading(true);
    try {
      setCandidate(await candidateApi.getCandidate(id));
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id]);

  async function handleSendInvite() {
    setSending(true);
    try {
      const res = await candidateApi.resendInvite(id);
      toast.success(res.detail);
      refresh();
    } catch (err) {
      toast.error(extractErrorMessage(err));
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

  if (loading || !candidate) return <div>Loading…</div>;

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
          <div className="field"><label>Aadhaar</label><div>{candidate.aadhaar_masked || '—'}</div></div>
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
          <table className="data-table">
            <thead><tr><th>Section</th><th>Score</th><th>Cutoff</th><th></th></tr></thead>
            <tbody>
              {candidate.section_results.map((row) => (
                <tr key={row.section}>
                  <td>{row.section}</td>
                  <td>{row.score != null ? `${row.score}/10` : '—'}</td>
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
          <div style={{ fontSize: 12.5, marginTop: 8 }}>
            <b>
              Overall: {candidate.overall_score != null
                ? `${candidate.overall_score}/${candidate.overall_total}`
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
                <a className="link-text" href={candidate.evidence.aadhaar_capture_url} download>⬇ Download</a>
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
                <a className="link-text" href={candidate.evidence.face_photo_url} download>⬇ Download</a>
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
                <a className="link-text" href={candidate.evidence.session_recording_url} download>⬇ Download</a>
              </div>
            ) : (
              <div style={{ textAlign: 'center', fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>Not yet recorded</div>
            )}
          </div>
        </div>
        {hasAnyEvidence && (
          <div className="btn-row no-print" style={{ marginTop: 12 }}>
            <button className="btn" onClick={handleDownloadZip} disabled={downloadingZip}>
              {downloadingZip ? 'Preparing…' : '⬇ Download All Evidence (ZIP)'}
            </button>
          </div>
        )}
        <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 10 }}>
          Populated once the candidate completes their proctored assessment.
        </div>
      </div>

      <div className="card" style={{ marginTop: 16 }}>
        <div className="box-label">Process / Status History</div>
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

      <div className="btn-row no-print" style={{ display: 'flex', gap: 10, marginTop: 16 }}>
        <button className="btn primary" onClick={handleSendInvite} disabled={sending}>
          {sending ? 'Sending…' : 'Send Invite Link'}
        </button>
        <button className="btn" onClick={() => window.print()}>🖨 Export Candidate Details (PDF)</button>
      </div>
    </div>
  );
}
