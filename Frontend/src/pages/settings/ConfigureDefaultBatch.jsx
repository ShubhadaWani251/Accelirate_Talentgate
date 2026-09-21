import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';

// Admin-only screen (route-gated in AppRouter, and the server independently enforces IsAdmin on
// GET/PUT /api/batches/defaults/ - this page is convenience, not the actual control).
//
// This is the ONE place the org-wide exam schedule/question counts/cutoffs are set. Every batch
// snapshots its own copy of these values the moment it's created (BatchListCreateView.post) and
// never rereads this config again, so a save here only ever affects batches created AFTER it -
// nothing already in flight changes, and nothing here can be used to adjust one specific batch
// (that's Batch Details' cutoffs-only edit).
//
// The section rows are rendered from whatever the server returns rather than from a fixed list
// of four: a section added on Question Bank Management has to be configurable here the moment
// it exists. That also rules out react-hook-form's static schema here - the field set is not
// known until the fetch resolves - so this form is plain controlled state with its own
// validation, which is small enough to be clearer than a dynamically-built resolver.
export default function ConfigureDefaultBatch() {
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [duration, setDuration] = useState('');
  const [sections, setSections] = useState([]);
  const [errors, setErrors] = useState({});

  useEffect(() => {
    batchApi.getBatchDefaults()
      .then((defaults) => {
        setDuration(String(defaults.exam_duration_minutes));
        setSections(defaults.sections.map((s) => ({
          ...s,
          question_count: String(s.question_count),
          cutoff: String(s.cutoff),
        })));

      })
      .catch((err) => toast.error(extractErrorMessage(err)))
      .finally(() => setLoading(false));
  }, []);

  function setSectionField(sectionKey, field, value) {
    setSections((rows) => rows.map(
      (row) => (row.section_key === sectionKey ? { ...row, [field]: value } : row),
    ));
  }

  function validate() {
    const found = {};
    if (!(Number(duration) >= 1)) found.exam_duration_minutes = 'Must be at least 1.';
    // Only the SELECTED sections are validated: an unselected one's inputs are hidden, and
    // refusing to save because of a value nobody can see would be unfixable from this screen.
    sections.filter((s) => s.included).forEach((s) => {
      if (!(Number(s.question_count) >= 1)) {
        found[`${s.section_key}_questions`] = 'Must be at least 1.';
      }
      const cutoff = Number(s.cutoff);
      if (!(cutoff >= 0 && cutoff <= 100) || s.cutoff === '') {
        found[`${s.section_key}_cutoff`] = 'Must be between 0 and 100.';
      }
    });
    if (sections.length > 0 && !sections.some((s) => s.included)) {
      found.sections = 'Select at least one section - a batch needs something to assess.';
    }
    setErrors(found);
    return Object.keys(found).length === 0;
  }

  async function onSubmit(event) {
    event.preventDefault();
    if (!validate()) return;
    setSubmitting(true);
    try {
      const saved = await batchApi.saveBatchDefaults({
        exam_duration_minutes: Number(duration),
        // Every section is sent, selected or not - an unselected one keeps its stored count and
        // cutoff so re-selecting it later restores what was configured rather than resetting it.
        sections: sections.map((s) => ({
          section_key: s.section_key,
          question_count: Number(s.question_count) || 1,
          cutoff: Number(s.cutoff) || 0,
          included: Boolean(s.included),
        })),
      });
      setDuration(String(saved.exam_duration_minutes));
      setSections(saved.sections.map((s) => ({
        ...s,
        question_count: String(s.question_count),
        cutoff: String(s.cutoff),
      })));
      // Drafts are re-synced server-side, so the count says what actually moved rather than
      // leaving an admin to discover it from a batch later.
      const drafts = saved.resynced_draft_batches || 0;
      toast.success(
        drafts > 0
          ? `Saved. ${drafts} draft batch${drafts === 1 ? '' : 'es'} updated to match; batches `
            + 'already sent out keep their own configuration.'
          : 'Saved. New batches created from now on will use this configuration.',
      );
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
          This is the schedule, sections, question counts and pass cutoffs every new batch is
          created with. <b>Draft batches are updated to match</b> — nothing has been sent to
          their candidates yet. Batches that have left Draft keep whatever was configured here
          at the moment they were created, so an exam already underway is never reshaped. To
          revise a single finalized batch's cutoffs, open that batch's own Details page instead.
        </div>

        {loading ? (
          <div style={{ fontSize: 12.5, color: 'var(--muted)' }}>Loading current defaults…</div>
        ) : (
          <form onSubmit={onSubmit} noValidate>
            <div className="field" style={{ maxWidth: 220 }}>
              <label htmlFor="exam_duration_minutes">Exam Duration (minutes)</label>
              <input id="exam_duration_minutes" type="number"
                className={errors.exam_duration_minutes ? 'has-error' : ''}
                value={duration} onChange={(e) => setDuration(e.target.value)} />
              {errors.exam_duration_minutes && (
                <div className="field-error">{errors.exam_duration_minutes}</div>
              )}
            </div>

            {sections.length === 0 ? (
              <div className="alert amber" style={{ textAlign: 'left' }}>
                No exam sections exist yet. Add one from Question Bank Management before creating
                a batch.
              </div>
            ) : (
              <>
                {/* Which sections a new batch gets. Unticking one hides its inputs rather than
                    greying them: an excluded section has no question count or cutoff to set,
                    and showing dead fields invites someone to fill them in and expect an
                    effect. The values are kept server-side, so re-ticking restores them. */}
                <div className="field">
                  <label>Sections in a New Batch</label>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px 20px', marginTop: 4 }}>
                    {sections.map((s) => (
                      <label key={s.section_key}
                             style={{ display: 'flex', alignItems: 'center', gap: 7, fontSize: 13 }}>
                        <input
                          type="checkbox"
                          checked={Boolean(s.included)}
                          onChange={() => setSectionField(s.section_key, 'included', !s.included)}
                        />
                        {s.section_name}
                      </label>
                    ))}
                  </div>
                  {errors.sections && <div className="field-error">{errors.sections}</div>}
                </div>

                <div className="grid-4">
                  {sections.filter((s) => s.included).map((s) => (
                    <div key={s.section_key} className="field">
                      <label htmlFor={`${s.section_key}_questions`}>
                        {s.section_name} Questions
                      </label>
                      <input id={`${s.section_key}_questions`} type="number"
                        className={errors[`${s.section_key}_questions`] ? 'has-error' : ''}
                        value={s.question_count}
                        onChange={(e) => setSectionField(s.section_key, 'question_count', e.target.value)} />
                      {errors[`${s.section_key}_questions`] && (
                        <div className="field-error">{errors[`${s.section_key}_questions`]}</div>
                      )}

                      <label htmlFor={`${s.section_key}_cutoff`} style={{ marginTop: 10 }}>
                        {s.section_name} Cutoff (%)
                      </label>
                      <input id={`${s.section_key}_cutoff`} type="number" step="0.01"
                        className={errors[`${s.section_key}_cutoff`] ? 'has-error' : ''}
                        value={s.cutoff}
                        onChange={(e) => setSectionField(s.section_key, 'cutoff', e.target.value)} />
                      {errors[`${s.section_key}_cutoff`] && (
                        <div className="field-error">{errors[`${s.section_key}_cutoff`]}</div>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}

            <div className="btn-row" style={{ display: 'flex', gap: 10, marginTop: 8 }}>
              <button type="button" className="btn" onClick={() => navigate(-1)}>Back</button>
              <button type="submit" className="btn primary"
                      disabled={submitting || sections.length === 0}>
                <ButtonSpinner loading={submitting}>Save Defaults</ButtonSpinner>
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
