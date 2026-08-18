import { useState } from 'react';

// Order matches the spreadsheet template, so a reviewer editing a row is looking at the same
// sequence of fields they see in Excel. `label` doubles as the error_fields key the server
// reports, so a field at fault is highlighted without a second mapping.
const EDITABLE = [
  { key: 'first_name', label: 'Name' },
  { key: 'last_name', label: 'Last Name' },
  { key: 'email', label: 'Email' },
  { key: 'phone', label: 'Mobile' },
  { key: 'aadhaar_number', label: 'Aadhaar Number', type: 'aadhaar' },
  { key: 'college_name', label: 'College Name' },
  { key: 'degree', label: 'Degree' },
  { key: 'stream', label: 'Stream' },
  { key: 'percentage', label: 'Percentage' },
  { key: 'passing_out_year', label: 'Passing Out Year' },
  { key: 'location', label: 'Location' },
];

const DUPLICATE_PILL = {
  new: 'green',
  previously_invited: 'amber',
  duplicate_cleared: 'amber',
  duplicate_within_window: 'red',
};

export default function CandidateErrorRow({
  row, onSave, onDelete, onViewHistory, saving,
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
  const cell = (label) => (errorFields.has(label) ? 'cell-error' : '');

  if (editing) {
    return (
      <tr>
        <td colSpan={14} style={{ background: 'var(--accent-soft)' }}>
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
            <button className="btn primary" onClick={save} disabled={saving}>
              {saving ? 'Revalidating…' : 'Save & Revalidate'}
            </button>
          </div>
        </td>
      </tr>
    );
  }

  return (
    <tr>
      <td>{row.upload_row_number ?? '—'}</td>
      <td className={cell('Name')}>{row.full_name || '(missing)'}</td>
      <td className={cell('Email')}>{row.email || '(missing)'}</td>
      <td className={cell('Mobile')}>{row.phone || '—'}</td>
      <td className={cell('Aadhaar Number')}>{row.aadhaar_masked || '(missing)'}</td>
      <td className={cell('College Name')}>{row.college_name || '(missing)'}</td>
      <td className={cell('Degree')}>{row.degree || '—'}</td>
      <td className={cell('Stream')}>{row.stream || '—'}</td>
      <td className={cell('Percentage')}>{row.percentage ?? '—'}</td>
      <td className={cell('Passing Out Year')}>{row.passing_out_year ?? '—'}</td>
      <td className={cell('Location')}>{row.location || '—'}</td>
      <td style={{ whiteSpace: 'normal', minWidth: 150, color: 'var(--red)' }}>
        {row.errors?.length ? row.errors.join(' · ') : '—'}
      </td>
      <td>
        <span className={`pill ${DUPLICATE_PILL[row.duplicate_status] || 'gray'}`}>
          {row.duplicate_status_display || 'Not Checked'}
        </span>
      </td>
      <td style={{ whiteSpace: 'nowrap' }}>
        <button className="btn small" onClick={() => onViewHistory(row)}>History</button>{' '}
        <button className="btn small" onClick={startEdit} disabled={saving}>Edit</button>{' '}
        <button className="btn small danger" onClick={() => onDelete(row)} disabled={saving}>
          Delete
        </button>
      </td>
    </tr>
  );
}
