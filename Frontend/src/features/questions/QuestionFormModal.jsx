import { useRef, useState } from 'react';
import toast from 'react-hot-toast';
import * as questionApi from '../../api/questionApi';
import ToggleSwitch from '../../components/common/ToggleSwitch';
import { extractErrorMessage } from '../../utils/passwordSchema';

const DIFFICULTIES = ['Easy', 'Medium', 'Hard'];

// Shared Add/Edit modal, same reuse pattern the wireframe uses for its single Edit-Question
// modal - `question` is null for Add, populated for Edit.
export default function QuestionFormModal({ question, sections, defaultSectionId, onClose, onSaved }) {
  const isEdit = Boolean(question);
  const [form, setForm] = useState({
    section: question?.section ?? defaultSectionId ?? sections[0]?.section_id ?? '',
    question_text: question?.question_text || '',
    option_a: question?.option_a || '',
    option_b: question?.option_b || '',
    option_c: question?.option_c || '',
    option_d: question?.option_d || '',
    correct_option: question?.correct_option || 'A',
    difficulty: question?.difficulty || 'Medium',
    marks: question?.marks ?? 1,
    status: question?.status || 'Active',
  });
  const [saving, setSaving] = useState(false);
  // A plain ref, not React state, so it's checked/set synchronously within the same click's
  // call stack - `saving` state alone isn't enough, since two clicks fired back-to-back can
  // both read the same pre-update `saving` value from the closure before React re-renders.
  const savingRef = useRef(false);

  function set(field, value) {
    setForm({ ...form, [field]: value });
  }

  const correctOptionChoices = [
    { value: 'A', label: `Option A${form.option_a ? ` (${form.option_a})` : ''}` },
    { value: 'B', label: `Option B${form.option_b ? ` (${form.option_b})` : ''}` },
    ...(form.option_c ? [{ value: 'C', label: `Option C (${form.option_c})` }] : []),
    ...(form.option_d ? [{ value: 'D', label: `Option D (${form.option_d})` }] : []),
  ];

  async function handleSave() {
    if (savingRef.current) return;
    savingRef.current = true;
    setSaving(true);
    try {
      const payload = { ...form, option_c: form.option_c || null, option_d: form.option_d || null };
      if (isEdit) {
        await questionApi.updateQuestion(question.question_id, payload);
        toast.success('Question updated.');
      } else {
        await questionApi.createQuestion(payload);
        toast.success('Question added.');
      }
      onSaved();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 520 }}>
        <h4>{isEdit ? `Edit Question — ${question.question_code}` : 'Add Question'}</h4>
        <p>Update question content, manage answer choices, or toggle active status.</p>

        <div className="field">
          <label>Question Text</label>
          <textarea rows={3} value={form.question_text} onChange={(e) => set('question_text', e.target.value)} />
        </div>

        <div className="grid-2">
          <div className="field">
            <label>Section</label>
            <select value={form.section} onChange={(e) => set('section', Number(e.target.value))}>
              {sections.map((s) => (
                <option key={s.section_id} value={s.section_id}>{s.section_name}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Difficulty</label>
            <select value={form.difficulty} onChange={(e) => set('difficulty', e.target.value)}>
              {DIFFICULTIES.map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
          </div>
        </div>

        <div className="card" style={{ background: '#fafbfd', padding: 14, marginBottom: 15 }}>
          <div className="box-label">Question Options</div>
          <div className="grid-2">
            <div className="field"><label>Option A</label><input value={form.option_a} onChange={(e) => set('option_a', e.target.value)} /></div>
            <div className="field"><label>Option B</label><input value={form.option_b} onChange={(e) => set('option_b', e.target.value)} /></div>
            <div className="field"><label>Option C</label><input value={form.option_c} onChange={(e) => set('option_c', e.target.value)} /></div>
            <div className="field"><label>Option D</label><input value={form.option_d} onChange={(e) => set('option_d', e.target.value)} /></div>
          </div>
          <div className="field" style={{ marginBottom: 0 }}>
            <label>Correct Answer</label>
            <select value={form.correct_option} onChange={(e) => set('correct_option', e.target.value)}>
              {correctOptionChoices.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </div>
        </div>

        <div className="grid-2" style={{ alignItems: 'center' }}>
          <div className="field" style={{ maxWidth: 120 }}>
            <label>Marks</label>
            <input type="number" min={1} value={form.marks} onChange={(e) => set('marks', e.target.value)} />
          </div>
          <div className="field">
            <label>Status</label>
            <ToggleSwitch
              checked={form.status === 'Active'}
              onChange={(checked) => set('status', checked ? 'Active' : 'Inactive')}
            />
          </div>
        </div>

        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn primary" onClick={handleSave} disabled={saving}>
            {saving ? 'Saving…' : '💾 Save Changes'}
          </button>
        </div>
      </div>
    </div>
  );
}
