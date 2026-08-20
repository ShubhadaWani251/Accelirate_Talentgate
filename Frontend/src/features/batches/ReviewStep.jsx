import { useEffect, useState } from 'react';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import CandidateHistoryModal from '../candidates/CandidateHistoryModal';
import { SkeletonTableRows } from '../../components/loading/Skeleton';
import { formatDateTime } from '../../utils/datetime';
import { extractErrorMessage } from '../../utils/passwordSchema';

// Green = safe to invite, amber = worth a look, red = needs a decision. Same three colours
// mean the same three things everywhere a duplicate status is shown.
const DUPLICATE_PILL = {
  new: 'green',
  previously_invited: 'amber',
  duplicate_cleared: 'amber',
  duplicate_within_window: 'red',
};

// A prior record with no attempt date means the candidate was invited before but never sat the
// assessment. Rendering that as "Batch 103 - —" reads like missing data; saying so is clearer,
// and it's the whole reason the row is amber rather than red.
function lastAttemptText(candidate) {
  const prior = candidate.last_attempt;
  if (!prior) return '—';
  if (!prior.date) return `${prior.batch_name} · not attempted`;
  return `${prior.batch_name} · ${formatDateTime(prior.date)}`;
}

// Step 4: the duplicate review and invite selection.
//
// There is deliberately NO Validation column here. Every row reaching this step has already
// passed validation - the previous step doesn't let you continue until its error list is empty -
// so a column that always read "OK" would be pure noise. What matters here is the Aadhaar match
// against history, and who gets an invite.
export default function ReviewStep({ batch, onFinalized }) {
  const [candidates, setCandidates] = useState([]);
  // ONE selection, shared by both actions - the button you press decides what happens to the
  // checked rows: Delete Selected removes them, Create Batch invites them. Two separate
  // checkbox columns for the same set of rows was just twice the clicking.
  const [selected, setSelected] = useState(new Set());
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [historyCandidate, setHistoryCandidate] = useState(null);

  function apply(payload) {
    setCandidates(payload.rows);
    // Drop ids that no longer exist, so a deleted row can't linger in the selection.
    const present = new Set(payload.rows.map((r) => r.candidate_id));
    setSelected((prev) => new Set([...prev].filter((id) => present.has(id))));
  }

  async function refresh() {
    setLoading(true);
    try {
      apply(await batchApi.getStagingCandidates(batch.batch_id));
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [batch.batch_id]);

  function toggle(id) {
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  async function handleDeleteSelected() {
    if (selected.size === 0) {
      toast.error('Check the rows you want to remove first.');
      return;
    }
    const count = selected.size;
    setBusy(true);
    try {
      apply(await batchApi.deleteCandidates(batch.batch_id, Array.from(selected)));
      toast.success(`${count} row(s) removed from this batch.`);
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  // Moves to "Send Invite - Confirmation" WITHOUT committing anything. The batch is only
  // finalized when the TA confirms on that screen, so "Back / Edit" comes back to a Draft that
  // is still fully editable. Finalizing here would lock the configuration behind the user's
  // back the moment they stepped forward.
  function handleFinalizeClick() {
    const selectedIds = Array.from(selected);
    if (selectedIds.length === 0) {
      toast.error('Check the candidates you want to invite first.');
      return;
    }

    onFinalized({
      batch_id: batch.batch_id,
      batch_name: batch.batch_name,
      college_name: batch.college_name,
      link_valid_from: batch.link_valid_from,
      link_valid_until: batch.link_valid_until,
      exam_duration_minutes: batch.exam_duration_minutes,
      total_questions: batch.logical_questions + batch.quantitative_questions
        + batch.verbal_questions + batch.programming_questions,
      logical_cutoff: batch.logical_cutoff,
      quantitative_cutoff: batch.quantitative_cutoff,
      verbal_cutoff: batch.verbal_cutoff,
      programming_cutoff: batch.programming_cutoff,
      selected_candidate_ids: selectedIds,
      selected_count: selectedIds.length,
      skipped_count: candidates.length - selectedIds.length,
      needs_finalize: batch.status === 'draft',
    });
  }

  const withinWindow = candidates.filter((c) => c.duplicate_status === 'duplicate_within_window').length;
  const previouslyInvited = candidates.filter((c) => c.duplicate_status === 'previously_invited').length;

  return (
    <div className="card">
      <div className="box-label">Upload Review — duplicate check &amp; invite selection</div>
      <div className="annot">
        Every row here has already passed validation. <b>Status</b> is the Aadhaar match against
        historical records; <b>History</b> opens that candidate&apos;s past attempt, or shows that
        none exists. Check the rows you want to act on, then either remove them or continue to
        invite them — anything left unchecked stays on the batch without being emailed.
      </div>

      <div className="btn-row" style={{ display: 'flex', gap: 10, alignItems: 'center',
                                       flexWrap: 'wrap', marginBottom: 12 }}>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5 }}>
          <input
            type="checkbox"
            checked={selected.size === candidates.length && candidates.length > 0}
            onChange={() => setSelected(selected.size === candidates.length
              ? new Set() : new Set(candidates.map((c) => c.candidate_id)))}
          />
          <b>Select All</b>
        </label>
        <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>
          {selected.size} of {candidates.length} selected
        </span>
        <span style={{ flex: 1 }} />
        <button className="btn danger" onClick={handleDeleteSelected}
                disabled={busy || selected.size === 0}>
          🗑 Delete Selected ({selected.size})
        </button>
      </div>

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th></th>
              <th>Row</th>
              <th>Name</th>
              <th>Email</th>
              <th>Aadhaar</th>
              <th>Status</th>
              <th>Last Attempt</th>
              <th>History</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <SkeletonTableRows rows={5} columns={8} />
            ) : candidates.length === 0 ? (
              <tr><td colSpan={8}>No candidates on this batch.</td></tr>
            ) : (
              candidates.map((c) => (
                <tr key={c.candidate_id}>
                  <td>
                    <input type="checkbox" checked={selected.has(c.candidate_id)}
                           onChange={() => toggle(c.candidate_id)} />
                  </td>
                  <td>{c.upload_row_number ?? '—'}</td>
                  <td>{c.full_name}</td>
                  <td>{c.email}</td>
                  <td>{c.aadhaar_masked}</td>
                  <td>
                    <span className={`pill ${DUPLICATE_PILL[c.duplicate_status] || 'gray'}`}>
                      {c.duplicate_status_display || 'Not Checked'}
                    </span>
                  </td>
                  <td>{lastAttemptText(c)}</td>
                  <td>
                    <button className="btn small" onClick={() => setHistoryCandidate(c)}>
                      History
                    </button>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {previouslyInvited > 0 && (
        <div className="alert" style={{ marginTop: 14 }}>
          {previouslyInvited} row(s) appear in an earlier batch but never sat the assessment —
          no cooling-off period applies. Safe to invite.
        </div>
      )}

      {withinWindow > 0 && (
        <div className="alert error" style={{ marginTop: 14 }}>
          {withinWindow} row(s) sat the assessment inside the cooling-off window. Leave them
          unchecked to skip them, or check them to invite anyway — it&apos;s your call.
        </div>
      )}

      <div className="btn-row" style={{ marginTop: 16 }}>
        <button className="btn primary" onClick={handleFinalizeClick}
                disabled={busy || candidates.length === 0}>
          Create Batch &amp; Proceed to Send Invite
        </button>
      </div>

      {historyCandidate && (
        <CandidateHistoryModal
          candidate={historyCandidate}
          onClose={() => setHistoryCandidate(null)}
        />
      )}
    </div>
  );
}
