import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { Skeleton, SkeletonCard, SkeletonPage } from '../../components/loading/Skeleton';
import BatchSetupStep from './BatchSetupStep';
import FixErrorsStep from './FixErrorsStep';
import ReviewStep from './ReviewStep';
import InviteConfirmationStep from './InviteConfirmationStep';
import { isResourceMissing } from '../../utils/apiError';
import {
  formatExpiryDate, formatTimeLeft, isExpiringSoon, parseExpiry,
} from '../../utils/draftExpiry';
import { extractErrorMessage } from '../../utils/passwordSchema';

// Validation and review are separate steps on purpose: step 2 lists only the rows that failed
// and is finished when that list is empty, which is what lets step 3 drop its Validation column.
//
// Configuring the exam (schedule/question counts/cutoffs) is not a step here at all any more -
// it's the admin-only org-wide default (services/batch_defaults.py), snapshotted onto the batch
// the moment it's created. Step 1 only identifies the batch and takes the candidate list; step 4
// is where the assessment link's window gets set, immediately before the invite goes out.
const STEPS = [
  { key: 'setup', label: '1. Batch Details' },
  { key: 'validate', label: '2. Validate Candidates' },
  { key: 'review', label: '3. Review and Confirmation' },
  { key: 'invite', label: '4. Review & Send Invite' },
];

// Serves two routes:
//   /batches/new          - start a new upload from step 1
//   /batches/:id/continue - pick an unfinished draft back up where it was left
//
// A draft is an upload in progress, so opening one puts you back in this wizard rather than on
// the Batch Details screen: Batch Details reports on a live batch (candidates, pass/fail,
// invites), and none of that exists yet for a draft.
export default function BatchWizard() {
  const navigate = useNavigate();
  const { id } = useParams();
  const [stepKey, setStepKey] = useState(id ? null : 'setup');
  const [batch, setBatch] = useState(null);
  const [finalizeSummary, setFinalizeSummary] = useState(null);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    (async () => {
      try {
        const existing = await batchApi.getBatch(id);
        if (cancelled) return;
        // Only a draft belongs in the wizard. Anything already finalized has a real Batch
        // Details page, so send it there instead of offering steps it has moved past.
        if (existing.status !== 'draft') {
          navigate(`/batches/${id}`, { replace: true });
          return;
        }
        setBatch(existing);
        // Resume at the first step that still has work: if candidates were uploaded before
        // this draft was abandoned, they're waiting to be validated.
        setStepKey(existing.total_candidates > 0 ? 'validate' : 'setup');
      } catch (err) {
        if (!cancelled) {
          // A draft that has passed its 24 hours is deleted by the backend and then 404s, so
          // that's the likely reason a resume link stops working - a bookmarked or stale link
          // to a draft someone left overnight. Say so, rather than "Not found".
          toast.error(
            isResourceMissing(err)
              ? 'That draft is no longer available — an unfinished draft is deleted 24 hours '
                + 'after it was created, along with any candidates uploaded to it.'
              : extractErrorMessage(err)
          );
          navigate('/batches', { replace: true });
        }
      }
    })();
    return () => { cancelled = true; };
  }, [id, navigate]);

  const stepIndex = STEPS.findIndex((s) => s.key === stepKey);
  // Null unless this is a draft, so it's absent for a brand-new wizard run too (no batch yet).
  const draftExpiresAt = parseExpiry(batch);
  const expiringSoon = isExpiringSoon(draftExpiresAt);

  // Waiting on getBatch to decide which step to resume at.
  if (!stepKey) {
    return (
      <div className="page-wide">
        <SkeletonPage label="Loading upload wizard…">
          <div className="wizard-steps">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} width={130} height={30} radius={999} />
            ))}
          </div>
          <SkeletonCard lines={4} />
        </SkeletonPage>
      </div>
    );
  }

  return (
    <div className="page-wide">
      <h3>
        {id ? `Continue Upload — ${batch?.batch_name ?? ''}` : 'Bulk Candidate Upload & Duplicate Review'}
      </h3>
      {id && (
        <div className="alert" style={{ marginBottom: 12 }}>
          This batch is still a <b>Draft</b> — it hasn&apos;t been created yet and no invites have
          gone out. Finish the remaining steps below, or leave it and come back to it later.
          {/* The deadline matters most right here, where someone is mid-upload and deciding
              whether to finish now or come back tomorrow - "come back later" has a limit. */}
          {draftExpiresAt && (
            <div style={{ marginTop: 8, fontSize: 12.5,
                         color: expiringSoon ? 'var(--brand-red)' : undefined }}>
              <b>{formatTimeLeft(draftExpiresAt)}</b> — an unfinished draft is deleted, along
              with any candidates uploaded to it, 24 hours after it was created
              ({formatExpiryDate(draftExpiresAt)}). Finalizing the batch stops that; editing it
              or uploading more candidates does not extend it.
            </div>
          )}
        </div>
      )}
      <div className="wizard-steps">
        {/* Clickable for the current step and any already-completed one - each is exactly
            equivalent to the "← Back to ..." button already on the step it lands on, just
            reachable in one click from anywhere instead of only from the step immediately
            after it. A step not yet reached stays inert: jumping to "4. Review & Send Invite"
            before Review has produced a finalizeSummary would land on a blank pane, since that
            step's render is gated on having one (see stepKey === 'invite' below). */}
        {STEPS.map((s, i) => (
          <button
            key={s.key}
            type="button"
            className={`wstep ${i === stepIndex ? 'active' : i < stepIndex ? 'done' : ''}`}
            disabled={i > stepIndex}
            onClick={() => setStepKey(s.key)}
          >
            {s.label}
          </button>
        ))}
      </div>

      {stepKey === 'setup' && (
        <>
          <BatchSetupStep
            existingBatch={batch}
            onCreated={setBatch}
            // Takes the batch as a parameter rather than reading this component's own `batch`
            // state - that state may not have caught up yet to a batch BatchSetupStep just
            // created in the same call, since setBatch (via onCreated above) only takes effect
            // on BatchWizard's NEXT render, and this closure is bound at the render BEFORE
            // that. Reading `batch` here for a batch created a moment ago could still see null.
            onUploaded={async (uploadedBatch) => {
              // Re-read the batch so the review step sees the new candidate count.
              try {
                setBatch(await batchApi.getBatch(uploadedBatch.batch_id));
              } catch { /* the validate step refetches its own rows regardless */ }
              setStepKey('validate');
            }}
          />
          {/* A resumed draft may already hold rows from an earlier upload - always offer the
              way forward rather than making another upload the only exit from this step. */}
          {id && batch && (
            <div className="btn-row" style={{ marginTop: 12 }}>
              <button className="btn" onClick={() => setStepKey('validate')}>
                Skip upload — validate the candidates already on this batch →
              </button>
            </div>
          )}
        </>
      )}

      {stepKey === 'validate' && batch && (
        <>
          <FixErrorsStep batch={batch} onDone={() => setStepKey('review')} />
          <div className="btn-row" style={{ marginTop: 12 }}>
            <button className="btn" onClick={() => setStepKey('setup')}>
              ← Upload another file
            </button>
          </div>
        </>
      )}

      {stepKey === 'review' && batch && (
        <>
          <ReviewStep
            batch={batch}
            onFinalized={(summary) => {
              setFinalizeSummary(summary);
              setStepKey('invite');
            }}
          />
          <div className="btn-row" style={{ marginTop: 12 }}>
            <button className="btn" onClick={() => setStepKey('validate')}>
              ← Back to validation
            </button>
          </div>
        </>
      )}

      {stepKey === 'invite' && finalizeSummary && (
        <InviteConfirmationStep
          summary={finalizeSummary}
          onBack={() => setStepKey('review')}
          onSent={() => navigate(`/batches/${finalizeSummary.batch_id}`)}
        />
      )}
    </div>
  );
}
