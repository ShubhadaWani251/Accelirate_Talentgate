import { useState } from 'react';
import toast from 'react-hot-toast';
import * as questionApi from '../../api/questionApi';
import { ButtonSpinner } from '../../components/loading/Spinner';
import { extractErrorMessage } from '../../utils/passwordSchema';

// Only the display name is asked for. The server derives section_key from it - that key is what
// every score row, score filter and export column is keyed on, so it has to stay stable and is
// not something an Admin should be picking by hand.
export default function AddSectionModal({ onClose, onCreated }) {
  const [name, setName] = useState('');
  const [minRequired, setMinRequired] = useState(50);
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    if (!name.trim()) {
      toast.error('Give the section a name.');
      return;
    }
    setSaving(true);
    try {
      const section = await questionApi.createSection({
        section_name: name.trim(),
        min_required_active: Number(minRequired) || 50,
      });
      toast.success(`"${section.section_name}" added.`);
      onCreated(section);
    } catch (err) {
      toast.error(extractErrorMessage(err, ['section_name', 'min_required_active']));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 440 }}>
        <h4>Add Section</h4>
        <p>
          A new section becomes available to <b>new</b> batches straight away, and gets its own
          column in the candidate tables and the Excel export. Batches that already exist keep
          the sections they were created with.
        </p>

        <div className="field">
          <label>Section Name</label>
          <input
            value={name}
            autoFocus
            placeholder="e.g. Data Interpretation"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleSave(); }}
          />
        </div>

        <div className="field">
          <label>Question Bank Health Threshold</label>
          <input
            type="number"
            min={1}
            value={minRequired}
            onChange={(e) => setMinRequired(e.target.value)}
          />
          {/* Same meaning as every other section's threshold - the dashboard warns when a
              section holds fewer active questions than this. */}
          <div style={{ fontSize: 11.5, color: 'var(--muted)', marginTop: 4 }}>
            The dashboard flags this section as under-stocked below this many active questions.
          </div>
        </div>

        <div className="alert amber" style={{ textAlign: 'left', marginTop: 4 }}>
          You will need to add questions to this section before a batch can use it — a batch
          cannot start an exam for a section with too few active questions.
        </div>

        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 12 }}>
          <button className="btn" onClick={onClose} disabled={saving}>Cancel</button>
          <button className="btn primary" onClick={handleSave} disabled={saving}>
            <ButtonSpinner loading={saving}>Add Section</ButtonSpinner>
          </button>
        </div>
      </div>
    </div>
  );
}
