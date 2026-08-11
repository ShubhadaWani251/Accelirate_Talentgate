import { useState } from 'react';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { formatDateTime } from '../../utils/datetime';
import { extractErrorMessage } from '../../utils/passwordSchema';

export default function InviteConfirmationStep({ summary, onSent }) {
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);

  async function handleConfirm() {
    setSending(true);
    try {
      const res = await batchApi.sendInvites(summary.batch_id);
      setResult(res);
      toast.success(res.detail);
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="card">
      <div className="box-label">Send Invite — Confirmation</div>

      {!result ? (
        <>
          <p>
            You are about to invite <strong>{summary.candidate_count} candidate(s)</strong> to{' '}
            <strong>{summary.batch_name}</strong> ({summary.college_name}).
          </p>
          <ul style={{ fontSize: 13, color: 'var(--muted)', lineHeight: 1.8 }}>
            <li>Active window: {formatDateTime(summary.link_valid_from)} – {formatDateTime(summary.link_valid_until)}</li>
            <li>Duration: {summary.exam_duration_minutes} minutes · {summary.total_questions} questions</li>
            <li>
              Cutoffs: Logical {summary.logical_cutoff}% · Quantitative {summary.quantitative_cutoff}% ·
              Verbal {summary.verbal_cutoff}% · Programming {summary.programming_cutoff}%
            </li>
            <li>Email will include: greeting, unique link, date/time window, duration, and instructions.</li>
          </ul>
          <div className="btn-row">
            <button className="btn primary" style={{ width: 'auto' }} onClick={handleConfirm} disabled={sending}>
              {sending ? 'Sending…' : 'Confirm & Send Invites'}
            </button>
          </div>
        </>
      ) : (
        <div className="alert success">
          {result.detail} Candidates will receive their assessment link by email.
        </div>
      )}
    </div>
  );
}
