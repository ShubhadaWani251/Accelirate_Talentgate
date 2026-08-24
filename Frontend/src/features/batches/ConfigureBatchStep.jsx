import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as yup from 'yup';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { toDatetimeLocalValue } from '../../utils/datetime';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';

const SECTIONS = [
  { key: 'logical', label: 'Logical & Analytical' },
  { key: 'quantitative', label: 'Quantitative' },
  { key: 'verbal', label: 'Verbal Ability' },
  { key: 'programming', label: 'Programming' },
];

// Only the cutoffs are ever actually submitted from this form (see onSubmit) - everything else
// here is read-only display. No validation is declared for the display-only fields; the cutoff
// bounds still are, since those are real input.
const schema = yup.object({
  logical_cutoff: yup.number().typeError('Required').min(0).max(100).required(),
  quantitative_cutoff: yup.number().typeError('Required').min(0).max(100).required(),
  verbal_cutoff: yup.number().typeError('Required').min(0).max(100).required(),
  programming_cutoff: yup.number().typeError('Required').min(0).max(100).required(),
});

// Read-only display of one batch's configuration, from its own Details page - the exam
// schedule, question counts and cutoffs it was created with (services/batch_defaults.py sets
// these org-wide; this component only ever shows what a specific batch already has).
//
// The one thing still editable per-batch is the section cutoffs, and only once the batch has
// left Draft: a TA may need to revise them after seeing how a cohort actually scored. That edit
// is scoped to this one batch's own row (a PATCH to /api/batches/<id>/) and never touches the
// org-wide defaults - editing one batch's cutoff must never reconfigure every other batch.
//
// `locked` (a deactivated batch) freezes even the cutoffs; short of that, `readOnly` covers
// everything else. Both are always true from this component's one caller (BatchDetail.jsx) -
// kept as separate props rather than collapsed into one, because they answer different
// questions ("has this batch left Draft" vs "is it deactivated") and BatchDetail computes them
// separately.
export default function ConfigureBatchStep({ onCreated, existingBatch, readOnly = false, locked = false }) {
  const cutoffsOnly = readOnly && !locked;
  const [submitting, setSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm({ resolver: yupResolver(schema) });

  useEffect(() => {
    reset({
      ...existingBatch,
      link_valid_from: toDatetimeLocalValue(existingBatch.link_valid_from),
      link_valid_until: toDatetimeLocalValue(existingBatch.link_valid_until),
    });
  }, [existingBatch, reset]);

  async function onSubmit(values) {
    setSubmitting(true);
    try {
      const batch = await batchApi.updateBatch(existingBatch.batch_id, {
        logical_cutoff: values.logical_cutoff,
        quantitative_cutoff: values.quantitative_cutoff,
        verbal_cutoff: values.verbal_cutoff,
        programming_cutoff: values.programming_cutoff,
      });
      onCreated(batch);
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="card">
      <div className="box-label">Configure Batch</div>
      {readOnly && (
        <div className="alert" style={{ marginBottom: 14 }}>
          {locked
            ? 'This batch is deactivated - its configuration is locked.'
            : 'This batch has been finalized. Candidates may already have sat the exam, so the '
              + 'schedule and question counts are locked - only the section cutoffs can still be changed.'}
        </div>
      )}
      <form onSubmit={handleSubmit(onSubmit)} noValidate>
        <fieldset disabled style={{ border: 'none', padding: 0, margin: 0 }}>
          <div className="grid-2">
            <div className="field">
              <label htmlFor="batch_name">Batch Name</label>
              <input id="batch_name" {...register('batch_name')} />
            </div>
            <div className="field">
              <label htmlFor="college_name">College Name</label>
              <input id="college_name" {...register('college_name')} />
            </div>
          </div>

          <div className="grid-2">
            <div className="field">
              <label htmlFor="link_valid_from">Link Valid From</label>
              <input id="link_valid_from" type="datetime-local" {...register('link_valid_from')} />
            </div>
            <div className="field">
              <label htmlFor="link_valid_until">Link Valid Until</label>
              <input id="link_valid_until" type="datetime-local" {...register('link_valid_until')} />
            </div>
          </div>

          <div className="field" style={{ maxWidth: 220 }}>
            <label htmlFor="exam_duration_minutes">Exam Duration (minutes)</label>
            <input id="exam_duration_minutes" type="number" {...register('exam_duration_minutes')} />
          </div>

          <div className="grid-4">
            {SECTIONS.map((s) => (
              <div key={s.key} className="field">
                <label htmlFor={`${s.key}_questions`}>{s.label} Questions</label>
                <input id={`${s.key}_questions`} type="number" {...register(`${s.key}_questions`)} />
              </div>
            ))}
          </div>
        </fieldset>

        {/* The one live sub-form: disabled only when the whole batch is locked (deactivated). */}
        <fieldset disabled={locked} style={{ border: 'none', padding: 0, margin: 0 }}>
          <div className="grid-4">
            {SECTIONS.map((s) => (
              <div key={s.key} className="field">
                <label htmlFor={`${s.key}_cutoff`}>{s.label} Cutoff (%)</label>
                <input id={`${s.key}_cutoff`} type="number" step="0.01"
                  className={errors[`${s.key}_cutoff`] ? 'has-error' : ''}
                  {...register(`${s.key}_cutoff`)} />
                {errors[`${s.key}_cutoff`] && <div className="field-error">{errors[`${s.key}_cutoff`].message}</div>}
              </div>
            ))}
          </div>
        </fieldset>

        {!locked && (
          <div className="btn-row" style={{ display: 'flex', gap: 10, marginTop: 8 }}>
            <button type="submit" className="btn primary" disabled={submitting}>
              <ButtonSpinner loading={submitting}>
                {cutoffsOnly ? 'Save Cutoffs' : 'Save Batch Configuration'}
              </ButtonSpinner>
            </button>
          </div>
        )}
      </form>
    </div>
  );
}
