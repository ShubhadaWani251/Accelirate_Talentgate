import { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { toDatetimeLocalValue } from '../../utils/datetime';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';
import CutoffReviewModal from './CutoffReviewModal';

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
//
// `canEditCutoffs` is a third, independent gate: cutoffs grade results, so revising one is a
// policy call reserved for admins, not something a TA does from this screen even though they can
// otherwise reach it. Kept apart from `locked`/`readOnly` because it answers yet another
// question ("is this viewer allowed to", not "has this batch left Draft") - the backend enforces
// the same rule (BatchDetailView.patch), so this only spares a TA a submit-then-403 round trip.
export default function ConfigureBatchStep({
  onCreated, existingBatch, readOnly = false, locked = false, canEditCutoffs = true,
}) {
  const cutoffsOnly = readOnly && !locked && canEditCutoffs;
  const [submitting, setSubmitting] = useState(false);
  // The review step between editing a cutoff and applying it. `preview` holds the server's
  // answer; null means the modal is closed. Submitting now goes through here rather than
  // straight to the PATCH - a cutoff change silently re-grades everyone who has already sat
  // the exam, and nothing used to say so before it happened.
  const [preview, setPreview] = useState(null);
  const [reviewing, setReviewing] = useState(false);
  // Cutoffs are per-section rows now, not four fixed fields, so they are held as local state
  // keyed by section - the field set isn't known until the batch loads. react-hook-form still
  // drives the read-only display fields above.
  const [cutoffs, setCutoffs] = useState({});
  const [cutoffErrors, setCutoffErrors] = useState({});
  const { register, reset } = useForm();
  const sections = existingBatch.sections || [];

  useEffect(() => {
    reset({
      ...existingBatch,
      link_valid_from: toDatetimeLocalValue(existingBatch.link_valid_from),
      link_valid_until: toDatetimeLocalValue(existingBatch.link_valid_until),
    });
    setCutoffs(Object.fromEntries(
      (existingBatch.sections || []).map((s) => [s.section_key, String(s.cutoff)]),
    ));
  }, [existingBatch, reset]);

  // The payload, built once so the preview and the apply can never be asked about different
  // numbers - which would make the review worthless in exactly the case it matters.
  function cutoffPayload() {
    return sections.map((s) => ({
      section_key: s.section_key,
      cutoff: Number(cutoffs[s.section_key]),
    }));
  }

  function validate() {
    const found = {};
    sections.forEach((s) => {
      const value = Number(cutoffs[s.section_key]);
      if (cutoffs[s.section_key] === '' || !(value >= 0 && value <= 100)) {
        found[s.section_key] = 'Must be between 0 and 100.';
      }
    });
    setCutoffErrors(found);
    return Object.keys(found).length === 0;
  }

  // Submitting opens the review rather than saving. Apply is in the modal.
  async function onSubmit(event) {
    event.preventDefault();
    if (!validate()) return;

    setReviewing(true);
    try {
      setPreview(await batchApi.previewBatchCutoffs(existingBatch.batch_id, cutoffPayload()));
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setReviewing(false);
    }
  }

  async function applyCutoffs() {
    setSubmitting(true);
    try {
      const batch = await batchApi.updateBatch(existingBatch.batch_id, {
        section_cutoffs: cutoffPayload(),
      });
      setPreview(null);
      // The count comes back from the PATCH itself, so this reports what was actually
      // re-graded rather than repeating what the preview predicted.
      const regraded = batch.regraded_candidates;
      toast.success(regraded
        ? `Cutoffs saved — ${regraded} candidate(s) re-graded.`
        : 'Cutoffs saved.');
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
            : canEditCutoffs
              ? 'This batch has been finalized. Candidates may already have sat the exam, so the '
                + 'schedule and question counts are locked - only the section cutoffs can still be changed.'
              : 'This batch has been finalized and its configuration is locked. Section cutoffs '
                + 'can only be changed by an admin.'}
        </div>
      )}
      <form onSubmit={onSubmit} noValidate>
        <fieldset disabled style={{ border: 'none', padding: 0, margin: 0 }}>
          <div className="field" style={{ maxWidth: 420 }}>
            <label htmlFor="batch_name">Batch Name</label>
            <input id="batch_name" {...register('batch_name')} />
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
            {sections.map((s) => (
              <div key={s.section_key} className="field">
                <label>{s.section_name} Questions</label>
                <input type="number" value={s.question_count} readOnly />
              </div>
            ))}
          </div>
        </fieldset>

        {/* The one live sub-form: disabled when the whole batch is locked (deactivated), or when
            this viewer isn't allowed to touch cutoffs at all (a TA, on a finalized batch). */}
        <fieldset disabled={locked || !canEditCutoffs} style={{ border: 'none', padding: 0, margin: 0 }}>
          <div className="grid-4">
            {sections.map((s) => (
              <div key={s.section_key} className="field">
                <label htmlFor={`${s.section_key}_cutoff`}>{s.section_name} Cutoff (%)</label>
                <input id={`${s.section_key}_cutoff`} type="number" step="0.01"
                  className={cutoffErrors[s.section_key] ? 'has-error' : ''}
                  value={cutoffs[s.section_key] ?? ''}
                  onChange={(e) => setCutoffs(
                    (prev) => ({ ...prev, [s.section_key]: e.target.value }),
                  )} />
                {cutoffErrors[s.section_key] && (
                  <div className="field-error">{cutoffErrors[s.section_key]}</div>
                )}
              </div>
            ))}
          </div>
        </fieldset>

        {!locked && canEditCutoffs && (
          <div className="btn-row" style={{ display: 'flex', gap: 10, marginTop: 8, alignItems: 'center' }}>
            {/* "Review" rather than "Save": the button no longer writes anything, and naming
                it Save while it opened a dialog would be the same surprise in reverse. */}
            <button type="submit" className="btn primary" disabled={reviewing || submitting}>
              <ButtonSpinner loading={reviewing}>
                {cutoffsOnly ? 'Review Cutoff Changes' : 'Review Batch Configuration'}
              </ButtonSpinner>
            </button>
            <span style={{ fontSize: 12, color: 'var(--muted)' }}>
              You&apos;ll see what changes before anything is saved.
            </span>
          </div>
        )}
      </form>

      {preview && (
        <CutoffReviewModal
          preview={preview}
          applying={submitting}
          onApply={applyCutoffs}
          onClose={() => setPreview(null)}
        />
      )}
    </div>
  );
}
