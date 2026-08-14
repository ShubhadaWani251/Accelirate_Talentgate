import { useState } from 'react';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { formatDateTime } from '../../utils/datetime';
import { extractErrorMessage } from '../../utils/passwordSchema';

// "Send Invite - Confirmation" from the wireframe. Nothing is committed until the TA confirms
// here: the batch is finalized AND the invites dispatched in the same action, so "Back / Edit"
// returns to a batch that's still a Draft and therefore still fully editable.
export default function InviteConfirmationStep({ summary, onBack, onSent }) {
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);

  const candidateIds = summary.selected_candidate_ids || [];
  const skipped = summary.skipped_count ?? 0;

  async function handleConfirm() {
    setSending(true);
    try {
      // Finalize first so a validation failure stops the send entirely rather than leaving a
      // half-committed batch. Skipped when the batch has already left Draft (re-inviting from
      // Batch Details), where there's nothing left to finalize.
      if (summary.needs_finalize) {
        await batchApi.finalizeBatch(summary.batch_id, candidateIds);
      }
      const res = await batchApi.sendInvites(summary.batch_id, candidateIds);
      setResult(res);
      toast.success(res.detail);
      onSent?.(res);
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setSending(false);
    }
  }

  if (result) {
    return (
      <div className="card">
        <div className="box-label">Send Invite — Confirmation</div>
        <div className="alert success">{result.detail}</div>
      </div>
    );
  }

  return (
    <div className="card" style={{ maxWidth: 480 }}>
      <div className="box-label">You are about to invite</div>
      <div style={{ fontSize: 13, marginBottom: 10 }}>
        <b>{summary.selected_count} candidate(s)</b> to <b>{summary.batch_name}</b>
      </div>
      <div style={{ fontSize: 12, color: 'var(--muted)', lineHeight: 1.7 }}>
        Active window: {formatDateTime(summary.link_valid_from)} – {formatDateTime(summary.link_valid_until)}<br />
        Duration: {summary.exam_duration_minutes} min · {summary.total_questions} questions ·
        Cutoff {summary.logical_cutoff}%/{summary.quantitative_cutoff}%/
        {summary.verbal_cutoff}%/{summary.programming_cutoff}% per section<br />
        Email will include: greeting, unique link, date/time window, duration, instructions,
        escalation contact
      </div>

      {skipped > 0 && (
        <div className="alert" style={{ marginTop: 12 }}>
          {skipped} uploaded row(s) were left unchecked and will not be emailed. They stay on the
          batch — you can invite them later by selecting them in the candidate table.
        </div>
      )}

      <div className="btn-row" style={{ display: 'flex', gap: 10, marginTop: 14 }}>
        <button className="btn" onClick={onBack} disabled={sending}>Back / Edit</button>
        <button className="btn primary" style={{ width: 'auto' }} onClick={handleConfirm} disabled={sending}>
          {sending ? 'Sending…' : 'Confirm & Send Invites'}
        </button>
      </div>
    </div>
  );
}
