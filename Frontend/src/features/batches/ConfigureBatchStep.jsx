import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as yup from 'yup';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { fromDatetimeLocalValue, toDatetimeLocalValue } from '../../utils/datetime';
import { extractErrorMessage } from '../../utils/passwordSchema';

const SECTIONS = [
  { key: 'logical', label: 'Logical & Analytical' },
  { key: 'quantitative', label: 'Quantitative' },
  { key: 'verbal', label: 'Verbal Ability' },
  { key: 'programming', label: 'Programming' },
];

const schema = yup.object({
  batch_name: yup.string().required('Batch name is required'),
  college_name: yup.string().required('College name is required'),
  link_valid_from: yup.string().required('Required'),
  link_valid_until: yup.string().required('Required')
    .test('after-from', 'Must be after Link Valid From', function (value) {
      return !value || !this.parent.link_valid_from || value > this.parent.link_valid_from;
    }),
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

export default function ConfigureBatchStep({ onCreated, existingBatch, readOnly = false }) {
  const [submitting, setSubmitting] = useState(false);
  const [savingDefaults, setSavingDefaults] = useState(false);
  const {
    register,
    handleSubmit,
    reset,
    getValues,
    formState: { errors },
  } = useForm({ resolver: yupResolver(schema) });

  useEffect(() => {
    if (existingBatch) {
      reset({
        ...existingBatch,
        link_valid_from: toDatetimeLocalValue(existingBatch.link_valid_from),
        link_valid_until: toDatetimeLocalValue(existingBatch.link_valid_until),
      });
      return;
    }
    batchApi.getBatchDefaults()
      .then((defaults) => {
        reset({
          batch_name: '',
          college_name: '',
          link_valid_from: '',
          link_valid_until: '',
          ...defaults,
        });
      })
      .catch((err) => toast.error(extractErrorMessage(err)));
  }, [existingBatch, reset]);

  async function onSubmit(values) {
    setSubmitting(true);
    try {
      const payload = {
        ...values,
        link_valid_from: fromDatetimeLocalValue(values.link_valid_from),
        link_valid_until: fromDatetimeLocalValue(values.link_valid_until),
      };
      const batch = existingBatch
        ? await batchApi.updateBatch(existingBatch.batch_id, payload)
        : await batchApi.createBatch(payload);
      onCreated(batch);
    } catch (err) {
      toast.error(extractErrorMessage(err, ['batch_name', 'college_name', 'link_valid_until']));
    } finally {
      setSubmitting(false);
    }
  }

  async function handleSaveDefaults() {
    setSavingDefaults(true);
    try {
      const values = getValues();
      await batchApi.saveBatchDefaults({
        exam_duration_minutes: values.exam_duration_minutes,
        logical_questions: values.logical_questions,
        quantitative_questions: values.quantitative_questions,
        verbal_questions: values.verbal_questions,
        programming_questions: values.programming_questions,
        logical_cutoff: values.logical_cutoff,
        quantitative_cutoff: values.quantitative_cutoff,
        verbal_cutoff: values.verbal_cutoff,
        programming_cutoff: values.programming_cutoff,
      });
      toast.success('Saved as default for new batches (this batch is unaffected).');
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setSavingDefaults(false);
    }
  }

  return (
    <div className="card">
      <div className="box-label">Configure Batch</div>
      {readOnly && (
        <div className="alert" style={{ marginBottom: 14 }}>
          This batch has been finalized - configuration is locked.
        </div>
      )}
      <form onSubmit={handleSubmit(onSubmit)} noValidate>
        <fieldset disabled={readOnly} style={{ border: 'none', padding: 0, margin: 0 }}>
          <div className="grid-2">
            <div className="field">
              <label htmlFor="batch_name">Batch Name</label>
              <input id="batch_name" className={errors.batch_name ? 'has-error' : ''} {...register('batch_name')} />
              {errors.batch_name && <div className="field-error">{errors.batch_name.message}</div>}
            </div>
            <div className="field">
              <label htmlFor="college_name">College Name</label>
              <input id="college_name" className={errors.college_name ? 'has-error' : ''} {...register('college_name')} />
              {errors.college_name && <div className="field-error">{errors.college_name.message}</div>}
            </div>
          </div>

          <div className="grid-2">
            <div className="field">
              <label htmlFor="link_valid_from">Link Valid From</label>
              <input id="link_valid_from" type="datetime-local"
                className={errors.link_valid_from ? 'has-error' : ''} {...register('link_valid_from')} />
              {errors.link_valid_from && <div className="field-error">{errors.link_valid_from.message}</div>}
            </div>
            <div className="field">
              <label htmlFor="link_valid_until">Link Valid Until</label>
              <input id="link_valid_until" type="datetime-local"
                className={errors.link_valid_until ? 'has-error' : ''} {...register('link_valid_until')} />
              {errors.link_valid_until && <div className="field-error">{errors.link_valid_until.message}</div>}
            </div>
          </div>

          <div className="field" style={{ maxWidth: 220 }}>
            <label htmlFor="exam_duration_minutes">Exam Duration (minutes)</label>
            <input id="exam_duration_minutes" type="number"
              className={errors.exam_duration_minutes ? 'has-error' : ''} {...register('exam_duration_minutes')} />
            {errors.exam_duration_minutes && <div className="field-error">{errors.exam_duration_minutes.message}</div>}
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
                {errors[`${s.key}_cutoff`] && <div className="field-error">{errors[`${s.key}_cutoff`].message}</div>}
              </div>
            ))}
          </div>
        </fieldset>

        <div className="btn-row" style={{ display: 'flex', gap: 10, marginTop: 8 }}>
          <button type="button" className="btn" onClick={handleSaveDefaults} disabled={savingDefaults}>
            {savingDefaults ? 'Saving…' : 'Save as Default for New Batches'}
          </button>
          {!readOnly && (
            <button type="submit" className="btn primary" style={{ width: 'auto' }} disabled={submitting}>
              {submitting ? 'Saving…' : existingBatch ? 'Save Batch Configuration' : 'Continue to Upload →'}
            </button>
          )}
        </div>
      </form>
    </div>
  );
}
