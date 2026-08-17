import { useState } from 'react';

const STATUS_PILL = { valid: 'green', invalid: 'red', duplicate: 'amber' };
const STATUS_LABEL = { valid: 'Valid', invalid: 'Invalid', duplicate: 'Duplicate' };

// Fields the reviewer can correct in place. `key` matches what the validate-rows API accepts,
// and `label` matches the error_fields the server reports, so a field with an error can be
// highlighted without a second mapping.
const EDITABLE = [
  { key: 'section', label: 'Section', type: 'section' },
  { key: 'question_text', label: 'Question Text', type: 'textarea' },
  { key: 'option_a', label: 'Option A' },
  { key: 'option_b', label: 'Option B' },
  { key: 'option_c', label: 'Option C' },
  { key: 'option_d', label: 'Option D' },
  { key: 'correct_option', label: 'Correct Answer', type: 'correct' },
  { key: 'difficulty', label: 'Difficulty', type: 'difficulty' },
  { key: 'marks', label: 'Marks', type: 'number' },
];

export default function QuestionValidationRow({ row, sections, onSave, saving }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(row);

  function startEdit() {
    setDraft(row);
    setEditing(true);
  }

  function save() {
    onSave(draft);
    setEditing(false);
  }

  const errorFields = new Set(row.error_fields || []);

  if (!editing) {
    return (
      <tr>
        <td>{row.row_number}</td>
        <td className={errorFields.has('Section') ? 'cell-error' : ''}>
          {row.section_name || row.section || '—'}
        </td>
        <td style={{ whiteSpace: 'normal', minWidth: 180 }}
            className={errorFields.has('Question Text') ? 'cell-error' : ''}>
          {row.question_text || '—'}
        </td>
        <td>{row.question_type}</td>
        <td className={errorFields.has('Correct Answer') ? 'cell-error' : ''}>
          {row.correct_option || '—'}
        </td>
        <td className={errorFields.has('Marks') ? 'cell-error' : ''}>{row.marks ?? '—'}</td>
        <td><span className={`pill ${STATUS_PILL[row.status]}`}>{STATUS_LABEL[row.status]}</span></td>
        <td style={{ whiteSpace: 'normal', minWidth: 200,
                     color: row.errors?.length ? 'var(--brand-red)' : undefined }}>
          {row.errors?.length ? row.errors.join(' ') : '—'}
        </td>
        <td><button className="btn small" onClick={startEdit} disabled={saving}>Edit</button></td>
      </tr>
    );
  }

  return (
    <tr>
      <td colSpan={9} style={{ background: 'var(--accent-soft)' }}>
        <div className="box-label" style={{ marginBottom: 8 }}>Editing row {row.row_number}</div>
        <div className="grid-3">
          {EDITABLE.map((f) => (
            <div key={f.key} className="field">
              <label>{f.label}</label>
              {f.type === 'section' ? (
                <select value={draft.section || ''}
                        onChange={(e) => setDraft({ ...draft, section: e.target.value })}>
                  <option value="">— pick a section —</option>
                  {sections.map((s) => (
                    <option key={s.section_id} value={s.section_name}>{s.section_name}</option>
                  ))}
                </select>
              ) : f.type === 'correct' ? (
                <select value={draft.correct_option || ''}
                        onChange={(e) => setDraft({ ...draft, correct_option: e.target.value })}>
                  <option value="">—</option>
                  {['A', 'B', 'C', 'D'].map((o) => <option key={o} value={o}>{o}</option>)}
                </select>
              ) : f.type === 'difficulty' ? (
                <select value={draft.difficulty || ''}
                        onChange={(e) => setDraft({ ...draft, difficulty: e.target.value })}>
                  <option value="">—</option>
                  {['Easy', 'Medium', 'Hard'].map((d) => <option key={d} value={d}>{d}</option>)}
                </select>
              ) : f.type === 'textarea' ? (
                <textarea rows={2} value={draft.question_text || ''}
                          className={errorFields.has(f.label) ? 'has-error' : ''}
                          onChange={(e) => setDraft({ ...draft, question_text: e.target.value })} />
              ) : (
                <input type={f.type === 'number' ? 'number' : 'text'}
                       value={draft[f.key] ?? ''}
                       className={errorFields.has(f.label) ? 'has-error' : ''}
                       onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })} />
              )}
            </div>
          ))}
        </div>
        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={() => setEditing(false)}>Cancel</button>
          <button className="btn primary" style={{ width: 'auto' }} onClick={save} disabled={saving}>
            {saving ? 'Revalidating…' : 'Save & Revalidate'}
          </button>
        </div>
      </td>
    </tr>
  );
}
