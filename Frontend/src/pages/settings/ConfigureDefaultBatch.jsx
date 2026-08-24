import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as yup from 'yup';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';

const SECTIONS = [
  { key: 'logical', label: 'Logical & Analytical' },
  { key: 'quantitative', label: 'Quantitative' },
  { key: 'verbal', label: 'Verbal Ability' },
  { key: 'programming', label: 'Programming' },
];

const schema = yup.object({
  exam_duration_minutes: yup.number().typeError('Required').min(1).required(),
  logical_questions: yup.number().typeError('Required').min(1).required(),
  quantitative_questions: yup.number().typeError('Required').min(1).required(),
  verbal_questions: yup.number().typeError('Required').min(1).required(),
  programming_questions: yup.number().typeError('Required').min(1).required(),
  logical_cutoff: yup.number().typeError('Required').min(0).max(100).required(),
  quantitative_cutoff: yup.number().typeError('Required').min(0).max(100).required(),
  verbal_cutoff: yup.number().typeError('Required').min(0).max(100).required(),
  programming_cutoff: yup.number().typeError('Required').min(0).max(100).required(),
});

// Admin-only screen (route-gated in AppRouter, and the server independently enforces IsAdmin on
// GET/PUT /api/batches/defaults/ - this page is convenience, not the actual control).
//
// This is the ONE place the org-wide exam schedule/question counts/cutoffs are set. Every batch
// snapshots its own copy of these values the moment it's created (BatchListCreateView.post) and
// never rereads this config again, so a save here only ever affects batches created AFTER it -
// nothing already in flight changes, and nothing here can be used to adjust one specific batch
// (that's ConfigureBatchStep's cutoffs-only edit, from that batch's own Details page).
export default function ConfigureDefaultBatch() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm({ resolver: yupResolver(schema) });

  useEffect(() => {
    batchApi.getBatchDefaults()
      .then((defaults) => reset(defaults))
      .catch((err) => toast.error(extractErrorMessage(err)))
      .finally(() => setLoading(false));
  }, [reset]);

  async function onSubmit(values) {
    setSubmitting(true);
    try {
      const saved = await batchApi.saveBatchDefaults(values);
      reset(saved);
      toast.success('Saved. New batches created from now on will use this configuration.');
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page-wide">
      <h3>Configure Default Batch</h3>
      {/* No maxWidth here - .page-wide (the outer div) already caps at min(80vw, 1600px), and
          this card should fill it like every other admin screen's main card does, rather than
          shrinking back down and leaving the rest of that width empty. */}
      <div className="card">
        <div className="box-label">Exam Configuration</div>
        <div className="alert" style={{ marginBottom: 14 }}>
          This is the schedule, question counts and pass cutoffs every new batch is created
          with. It does not change any batch that already exists - each one keeps whatever was
          configured here at the moment it was created. To revise a single already-finalized
          batch's cutoffs, open that batch's own Details page instead.
        </div>

        {loading ? (
          <div style={{ fontSize: 12.5, color: 'var(--muted)' }}>Loading current defaults…</div>
        ) : (
          <form onSubmit={handleSubmit(onSubmit)} noValidate>
            <div className="field" style={{ maxWidth: 220 }}>
              <label htmlFor="exam_duration_minutes">Exam Duration (minutes)</label>
              <input id="exam_duration_minutes" type="number"
                className={errors.exam_duration_minutes ? 'has-error' : ''}
                {...register('exam_duration_minutes')} />
              {errors.exam_duration_minutes && (
                <div className="field-error">{errors.exam_duration_minutes.message}</div>
              )}
            </div>

            <div className="grid-4">
              {SECTIONS.map((s) => (
                <div key={s.key} className="field">
                  <label htmlFor={`${s.key}_questions`}>{s.label} Questions</label>
                  <input id={`${s.key}_questions`} type="number"
                    className={errors[`${s.key}_questions`] ? 'has-error' : ''}
                    {...register(`${s.key}_questions`)} />
                  {errors[`${s.key}_questions`] && (
                    <div className="field-error">{errors[`${s.key}_questions`].message}</div>
                  )}
                </div>
              ))}
            </div>

            <div className="grid-4">
              {SECTIONS.map((s) => (
                <div key={s.key} className="field">
                  <label htmlFor={`${s.key}_cutoff`}>{s.label} Cutoff (%)</label>
                  <input id={`${s.key}_cutoff`} type="number" step="0.01"
                    className={errors[`${s.key}_cutoff`] ? 'has-error' : ''}
                    {...register(`${s.key}_cutoff`)} />
                  {errors[`${s.key}_cutoff`] && (
                    <div className="field-error">{errors[`${s.key}_cutoff`].message}</div>
                  )}
                </div>
              ))}
            </div>

            <div className="btn-row" style={{ display: 'flex', gap: 10, marginTop: 8 }}>
              <button type="button" className="btn" onClick={() => navigate(-1)}>Back</button>
              <button type="submit" className="btn primary" disabled={submitting}>
                <ButtonSpinner loading={submitting}>Save Defaults</ButtonSpinner>
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
