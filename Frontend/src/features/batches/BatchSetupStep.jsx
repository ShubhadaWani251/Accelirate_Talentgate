import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as yup from 'yup';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';
import UploadStep from './UploadStep';

const schema = yup.object({
  batch_name: yup.string().required('Batch name is required'),
});

// Step 1 of the wizard, in two sequential phases: name the batch, then - once it exists -
// upload a candidate file against it. Two screens, not one, and not a single combined submit:
// the batch has to exist before UploadStep has anywhere to attach a file, so this shows exactly
// one of the two at a time rather than both fields together.
//
// The exam schedule/question counts/cutoffs no longer belong here at all: they come from the
// admin-configured org-wide default (services/batch_defaults.py) and are snapshotted onto the
// batch the moment it's created (BatchListCreateView.post) - nothing on this screen can set or
// see them.
//
// `existingBatch` covers resuming a draft that already has a name but no candidates yet
// (BatchWizard sends a draft with total_candidates === 0 straight to this step) - there is
// nothing left to name, so it goes straight to the same upload phase a fresh batch reaches
// after its name is submitted.
export default function BatchSetupStep({ existingBatch, onCreated, onUploaded }) {
  const [createdBatch, setCreatedBatch] = useState(existingBatch || null);
  const [submitting, setSubmitting] = useState(false);
  // A resumed draft skips straight to the upload phase below (createdBatch is already set from
  // existingBatch), which used to mean the name form - the only place batch_name was ever
  // editable - never rendered for it at all. A typo made while creating the batch had no way
  // back short of abandoning the draft. This is that way back, in place rather than a detour to
  // another screen.
  const [editingName, setEditingName] = useState(false);
  const [nameDraft, setNameDraft] = useState('');
  const [savingName, setSavingName] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm({ resolver: yupResolver(schema) });

  // Tells BatchWizard about the batch as soon as one exists, whichever way that happened - just
  // created here, or already existing because this is a resumed draft. FixErrorsStep/ReviewStep/
  // InviteConfirmationStep all read `batch` from the wizard's own state, not from here.
  useEffect(() => {
    if (createdBatch) onCreated(createdBatch);
  }, [createdBatch, onCreated]);

  async function onSubmit(values) {
    setSubmitting(true);
    try {
      const batch = await batchApi.createBatch(values);
      setCreatedBatch(batch);
    } catch (err) {
      toast.error(extractErrorMessage(err, ['batch_name']));
    } finally {
      setSubmitting(false);
    }
  }

  function startEditName() {
    setNameDraft(createdBatch.batch_name);
    setEditingName(true);
  }

  async function saveName() {
    setSavingName(true);
    try {
      const updated = await batchApi.updateBatch(createdBatch.batch_id, {
        batch_name: nameDraft.trim(),
      });
      setCreatedBatch(updated);
      setEditingName(false);
      toast.success('Batch name updated.');
    } catch (err) {
      toast.error(extractErrorMessage(err, ['batch_name']));
    } finally {
      setSavingName(false);
    }
  }

  // Once a batch exists - just created, or resumed - the name phase is done; hand off to the
  // upload phase. Reusing UploadStep directly rather than reimplementing its drag-drop/template
  // download/missing-column handling here. The name itself stays editable above it (see
  // editingName above) rather than only at creation time.
  if (createdBatch) {
    return (
      <>
        <div className="card" style={{ marginBottom: 16 }}>
          <div className="box-label">Batch Name</div>
          {editingName ? (
            <div className="field" style={{ maxWidth: 420 }}>
              <input value={nameDraft} onChange={(e) => setNameDraft(e.target.value)}
                autoFocus />
              <div className="btn-row" style={{ marginTop: 8 }}>
                <button type="button" className="btn" onClick={() => setEditingName(false)}
                  disabled={savingName}>
                  Cancel
                </button>
                <button type="button" className="btn primary" onClick={saveName}
                  disabled={savingName || !nameDraft.trim()}>
                  <ButtonSpinner loading={savingName}>Save</ButtonSpinner>
                </button>
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span>{createdBatch.batch_name}</span>
              <button type="button" className="btn small" onClick={startEditName}>Edit</button>
            </div>
          )}
        </div>
        <UploadStep batch={createdBatch} onUploaded={onUploaded} />
      </>
    );
  }

  return (
    <div className="card">
      <div className="box-label">Batch Details</div>
      <form onSubmit={handleSubmit(onSubmit)} noValidate>
        <div className="field" style={{ maxWidth: 420 }}>
          <label htmlFor="batch_name">Batch Name</label>
          <input id="batch_name" className={errors.batch_name ? 'has-error' : ''}
            {...register('batch_name')} />
          {errors.batch_name && <div className="field-error">{errors.batch_name.message}</div>}
        </div>

        <div className="btn-row" style={{ marginTop: 8 }}>
          <button type="submit" className="btn primary" disabled={submitting}>
            <ButtonSpinner loading={submitting}>Continue to Upload →</ButtonSpinner>
          </button>
        </div>
      </form>
    </div>
  );
}
