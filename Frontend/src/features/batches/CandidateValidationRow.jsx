import { useState } from 'react';
import { formatDateTime } from '../../utils/datetime';

const VALIDATION_PILL = { ok: 'green' };
const DUPLICATE_PILL = {
  new: 'gray',
  // Seen before but never sat the assessment - informational, not a blocker.
  previously_invited: 'amber',
  duplicate_cleared: 'amber',
  duplicate_within_window: 'red',
};

// `key` is what the PATCH endpoint accepts; `label` matches the error_fields the server
// reports, so a field at fault can be highlighted without a second mapping. Same arrangement
// as QuestionValidationRow.
const EDITABLE = [
  { key: 'first_name', label: 'First Name' },
  { key: 'last_name', label: 'Last Name' },
  { key: 'email', label: 'Email', type: 'email' },
  { key: 'phone', label: 'Mobile' },
  { key: 'aadhaar_number', label: 'Aadhaar Number', type: 'aadhaar' },
  { key: 'college_name', label: 'College Name' },
  { key: 'degree', label: 'Degree' },
  { key: 'stream', label: 'Stream' },
  { key: 'percentage', label: 'Percentage', type: 'number' },
  { key: 'passing_out_year', label: 'Passing Out Year', type: 'number' },
  { key: 'location', label: 'Location' },
];

function Pill({ text, color }) {
  return <span className={`pill ${color}`}>{text}</span>;
}

export default function CandidateValidationRow({
  row, selected, onToggleSelected, onSave, onViewHistory, saving, editable,
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({});

  function startEdit() {
    // Aadhaar is deliberately absent: the browser only ever receives the masked number, so
    // the box starts empty and an empty box means "leave it alone".
    setDraft({
      first_name: row.first_name || '',
      last_name: row.last_name || '',
      email: row.email || '',
      phone: row.phone || '',
      aadhaar_number: '',
      college_name: row.college_name || '',
      degree: row.degree || '',
      stream: row.stream || '',
      percentage: row.percentage ?? '',
      passing_out_year: row.passing_out_year ?? '',
      location: row.location || '',
    });
    setEditing(true);
  }

  async function save() {
    const payload = { ...draft };
    if (!payload.aadhaar_number) delete payload.aadhaar_number;
    const ok = await onSave(row.candidate_id, payload);
    if (ok) setEditing(false);
  }

  const errorFields = new Set(row.error_fields || []);

  if (editing) {
    return (
      <tr>
        <td colSpan={12} style={{ background: 'var(--accent-soft)' }}>
          <div className="box-label" style={{ marginBottom: 8 }}>
            Editing row {row.upload_row_number ?? row.candidate_id}
          </div>
          <div className="grid-3">
            {EDITABLE.map((f) => (
              <div key={f.key} className="field">
                <label>
                  {f.label}
                  {f.type === 'aadhaar' && (
                    <span style={{ color: 'var(--muted)', fontWeight: 400 }}>
                      {' '}— currently {row.aadhaar_masked || 'not set'}
                    </span>
                  )}
                </label>
                <input
                  type={f.type === 'number' ? 'number' : 'text'}
                  value={draft[f.key] ?? ''}
                  className={errorFields.has(f.label) ? 'has-error' : ''}
                  placeholder={f.type === 'aadhaar' ? 'Leave blank to keep the current number' : ''}
                  onChange={(e) => setDraft({ ...draft, [f.key]: e.target.value })}
                />
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

  return (
    <tr>
      <td>
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggleSelected(row.candidate_id)}
        />
      </td>
      <td>{row.upload_row_number ?? '—'}</td>
      <td className={errorFields.has('First Name') ? 'cell-error' : ''}>
        {row.full_name || '(missing)'}
      </td>
      <td className={errorFields.has('Email') ? 'cell-error' : ''}>
        {row.email || '(missing)'}
      </td>
      <td className={errorFields.has('Mobile') ? 'cell-error' : ''}>
        {row.phone || '—'}
      </td>
      <td className={errorFields.has('Aadhaar Number') ? 'cell-error' : ''}>
        {row.aadhaar_masked || '(missing)'}
      </td>
      <td>
        <Pill
          text={row.validation_status_display}
          color={VALIDATION_PILL[row.validation_status] || 'red'}
        />
      </td>
      <td style={{ whiteSpace: 'normal', minWidth: 200,
                   color: row.errors?.length ? 'var(--brand-red)' : undefined }}>
        {row.errors?.length ? row.errors.join(' ') : '—'}
      </td>
      <td>
        <Pill
          text={row.duplicate_status_display}
          color={DUPLICATE_PILL[row.duplicate_status] || 'gray'}
        />
      </td>
      <td>
        {row.last_attempt
          ? `${row.last_attempt.batch_name} · ${formatDateTime(row.last_attempt.date)}`
          : '—'}
      </td>
      <td>
        <button className="btn small" onClick={() => onViewHistory(row)}>View History</button>
      </td>
      <td>
        <button className="btn small" onClick={startEdit} disabled={saving || !editable}>
          Edit
        </button>
      </td>
    </tr>
  );
}
