import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import ConfigureBatchStep from './ConfigureBatchStep';
import UploadStep from './UploadStep';
import FixErrorsStep from './FixErrorsStep';
import ReviewStep from './ReviewStep';
import InviteConfirmationStep from './InviteConfirmationStep';
import { extractErrorMessage } from '../../utils/passwordSchema';

// Validation and review are separate steps on purpose: step 3 lists only the rows that failed
// and is finished when that list is empty, which is what lets step 4 drop its Validation column.
const STEPS = [
  { key: 'configure', label: '1. Configure Batch' },
  { key: 'upload', label: '2. Upload Excel' },
  { key: 'validate', label: '3. Validate Candidates' },
  { key: 'review', label: '4. Upload Review' },
  { key: 'invite', label: '5. Send Invite' },
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
  const [stepKey, setStepKey] = useState(id ? null : 'configure');
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
        setStepKey(existing.total_candidates > 0 ? 'validate' : 'upload');
      } catch (err) {
        if (!cancelled) {
          toast.error(extractErrorMessage(err));
          navigate('/batches', { replace: true });
        }
      }
    })();
    return () => { cancelled = true; };
  }, [id, navigate]);

  const stepIndex = STEPS.findIndex((s) => s.key === stepKey);

  if (!stepKey) return <div>Loading…</div>;

  return (
    <div className="page-wide">
      <h3>
        {id ? `Continue Upload — ${batch?.batch_name ?? ''}` : 'Bulk Candidate Upload & Duplicate Review'}
      </h3>
      {id && (
        <div className="alert" style={{ marginBottom: 12 }}>
          This batch is still a <b>Draft</b> — it hasn&apos;t been created yet and no invites have
          gone out. Finish the remaining steps below, or leave it and come back to it later.
        </div>
      )}
      <div className="wizard-steps">
        {STEPS.map((s, i) => (
          <span key={s.key} className={`wstep ${i === stepIndex ? 'active' : i < stepIndex ? 'done' : ''}`}>
            {s.label}
          </span>
        ))}
      </div>

      {stepKey === 'configure' && (
        <ConfigureBatchStep
          onCreated={(createdBatch) => {
            setBatch(createdBatch);
            setStepKey('upload');
          }}
        />
      )}

      {/* A resumed draft can still have its configuration corrected - it's a draft, nothing is
          committed. A brand-new one has just come through this step, so it isn't shown twice. */}
      {id && batch && stepKey !== 'invite' && (
        <ConfigureBatchStep existingBatch={batch} onCreated={setBatch} />
      )}

      {stepKey === 'upload' && batch && (
        <>
          <UploadStep
            batch={batch}
            onUploaded={async () => {
              // Re-read the batch so the review step sees the new candidate count.
              try {
                setBatch(await batchApi.getBatch(batch.batch_id));
              } catch { /* the validate step refetches its own rows regardless */ }
              setStepKey('validate');
            }}
          />
          {/* A resumed draft may already hold rows from an earlier upload - always offer the
              way forward rather than making another upload the only exit from this step. */}
          {id && (
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
            <button className="btn" onClick={() => setStepKey('upload')}>
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
