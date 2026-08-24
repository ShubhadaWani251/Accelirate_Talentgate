import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as yup from 'yup';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { fromDatetimeLocalValue, toDatetimeLocalValue } from '../../utils/datetime';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';

// Same four sections, same order, as ConfigureDefaultBatch.jsx and ConfigureBatchStep.jsx - the
// grid below is deliberately built to look like those screens, since this is showing exactly
// the values one of them produced.
const SECTIONS = [
  { key: 'logical', label: 'Logical & Analytical' },
  { key: 'quantitative', label: 'Quantitative' },
  { key: 'verbal', label: 'Verbal Ability' },
  { key: 'programming', label: 'Programming' },
];

const schema = yup.object({
  link_valid_from: yup.string().required('Required'),
  link_valid_until: yup.string().required('Required')
    .test('after-from', 'Must be after Link Valid From', function (value) {
      return !value || !this.parent.link_valid_from || value > this.parent.link_valid_from;
    })
    // Mirrors BatchSerializer.validate/link_window_error, which is what actually enforces this -
    // repeated here only so the warning shows on the field as it's being typed, instead of
    // arriving as a toast after the PATCH below has already round-tripped to the server.
    .test('covers-exam', function (value) {
      const { link_valid_from: from } = this.parent;
      const duration = this.options.context?.durationMinutes;
      if (!value || !from || !duration) return true;
      const windowMinutes = (new Date(value) - new Date(from)) / 60000;
      if (!Number.isFinite(windowMinutes) || windowMinutes >= duration) return true;
      return this.createError({
        message: `Warning: only ${Math.round(windowMinutes)} minutes long, but the exam runs `
          + `for ${duration}. A candidate reconnecting mid-exam would be locked out - make this `
          + `at least ${duration} minutes after the start.`,
      });
    }),
});

// "Send Invite - Confirmation" from the wireframe, now also where the assessment link's window
// is actually set - it used to be collected upfront on the old Configure Batch step, but the
// schedule/question counts/cutoffs shown below are the admin-configured default (see
// BatchSetupStep), which never included a per-batch window. This is the first and only point in
// the flow that does.
//
// Nothing is committed until confirmed here: the window is saved, then (if still Draft) the
// batch is finalized, then invites are sent, in that order - a validation failure on any step
// stops the ones after it, so "Back / Edit" always returns to an unmodified Draft.
export default function InviteConfirmationStep({ summary, onBack, onSent }) {
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState(null);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm({
    resolver: yupResolver(schema),
    context: { durationMinutes: summary.exam_duration_minutes },
    defaultValues: {
      link_valid_from: toDatetimeLocalValue(summary.link_valid_from),
      link_valid_until: toDatetimeLocalValue(summary.link_valid_until),
    },
  });

  const candidateIds = summary.selected_candidate_ids || [];
  const skipped = summary.skipped_count ?? 0;

  async function onConfirm(values) {
    setSending(true);
    try {
      // The window first: if it's rejected server-side too (belt and braces - the client check
      // above mirrors but does not replace it), nothing else below runs and the batch is
      // untouched.
      await batchApi.updateBatch(summary.batch_id, {
        link_valid_from: fromDatetimeLocalValue(values.link_valid_from),
        link_valid_until: fromDatetimeLocalValue(values.link_valid_until),
      });
      // Skipped when the batch has already left Draft (re-inviting more candidates from Batch
      // Details), where there's nothing left to finalize.
      if (summary.needs_finalize) {
        await batchApi.finalizeBatch(summary.batch_id, candidateIds);
      }
      const res = await batchApi.sendInvites(summary.batch_id, candidateIds);
      setResult(res);
      toast.success(res.detail);
      onSent?.(res);
    } catch (err) {
      toast.error(extractErrorMessage(err, ['link_valid_from', 'link_valid_until']));
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
    <div className="card">
      <div className="box-label">Review Configuration &amp; Send Invite</div>
      <div style={{ fontSize: 13, marginBottom: 14 }}>
        <b>{summary.selected_count} candidate(s)</b> to <b>{summary.batch_name}</b>
      </div>

      {/* View only, in the same structured layout as the admin's Configure Default Batch
          screen - these are exactly the values that screen produced, snapshotted onto this
          batch at creation, and nothing here can change them. The cutoffs are the one exception
          to "fixed forever": they stay adjustable, but from the batch's own Details page once
          it's live, not from here. */}
      <fieldset disabled style={{ border: 'none', padding: 0, margin: 0 }}>
        <div className="field" style={{ maxWidth: 220 }}>
          <label htmlFor="review_exam_duration_minutes">Exam Duration (minutes)</label>
          <input id="review_exam_duration_minutes" value={summary.exam_duration_minutes} readOnly />
        </div>

        <div className="grid-4">
          {SECTIONS.map((s) => (
            <div key={s.key} className="field">
              <label htmlFor={`review_${s.key}_questions`}>{s.label} Questions</label>
              <input id={`review_${s.key}_questions`}
                value={summary[`${s.key}_questions`]} readOnly />
            </div>
          ))}
        </div>

        <div className="grid-4">
          {SECTIONS.map((s) => (
            <div key={s.key} className="field">
              <label htmlFor={`review_${s.key}_cutoff`}>{s.label} Cutoff (%)</label>
              <input id={`review_${s.key}_cutoff`}
                value={summary[`${s.key}_cutoff`]} readOnly />
            </div>
          ))}
        </div>
      </fieldset>

      <div style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4, marginBottom: 14 }}>
        Email will include: greeting, unique link, date/time window, duration, instructions,
        escalation contact
      </div>

      <form onSubmit={handleSubmit(onConfirm)} noValidate>
        <div className="grid-2">
          <div className="field">
            <label htmlFor="link_valid_from">Link Valid From</label>
            <input id="link_valid_from" type="datetime-local"
              className={errors.link_valid_from ? 'has-error' : ''}
              {...register('link_valid_from')} />
            {errors.link_valid_from && (
              <div className="field-error">{errors.link_valid_from.message}</div>
            )}
          </div>
          <div className="field">
            <label htmlFor="link_valid_until">Link Valid Until</label>
            <input id="link_valid_until" type="datetime-local"
              className={errors.link_valid_until ? 'has-error' : ''}
              {...register('link_valid_until')} />
            {errors.link_valid_until && (
              <div className="field-error">{errors.link_valid_until.message}</div>
            )}
          </div>
        </div>

        {skipped > 0 && (
          <div className="alert" style={{ marginTop: 12 }}>
            {skipped} uploaded row(s) were left unchecked and will not be emailed. They stay on
            the batch — you can invite them later by selecting them in the candidate table.
          </div>
        )}

        <div className="btn-row" style={{ display: 'flex', gap: 10, marginTop: 14 }}>
          <button type="button" className="btn" onClick={onBack} disabled={sending}>Back / Edit</button>
          <button type="submit" className="btn primary" disabled={sending}>
            <ButtonSpinner loading={sending}>Confirm & Send Invites</ButtonSpinner>
          </button>
        </div>
      </form>
    </div>
  );
}
