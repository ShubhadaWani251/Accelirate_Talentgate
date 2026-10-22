import { useState } from 'react';
import toast from 'react-hot-toast';
import * as questionApi from '../../api/questionApi';
import { ButtonSpinner } from '../../components/loading/Spinner';
import { extractErrorMessage } from '../../utils/passwordSchema';

// Only the display name is asked for. The server derives section_key from it - that key is what
// every score row, score filter and export column is keyed on, so it has to stay stable and is
// not something an Admin should be picking by hand.
//
// The health threshold is not asked for either. It only tuned when the dashboard's Question Bank
// Health panel calls a section under-stocked, which is advisory and blocks nothing - the real
// gate is the per-batch question count, enforced at finalize. Asking for it made a number up
// front for a warning nobody had seen yet, and per-section values would have contradicted that
// panel's own "min. 50 active each" heading. Every section now uses the server's default.
export default function AddSectionModal({ onClose, onCreated }) {
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);

  async function handleSave() {
    if (!name.trim()) {
      toast.error('Give the section a name.');
      return;
    }
    setSaving(true);
    try {
      const section = await questionApi.createSection({ section_name: name.trim() });
      toast.success(`"${section.section_name}" added.`);
      onCreated(section);
    } catch (err) {
      toast.error(extractErrorMessage(err, ['section_name']));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 440 }}>
        <h4>Add Section</h4>
        <p style={{ marginBottom: 10 }}>
          New batches can use this section right away. It will also get its own column in the
          candidate tables and the Excel export.
        </p>
        {/* "Existing" covers Drafts here, which is NOT how the rest of this screen behaves and
            is worth being exact about: deactivating or restoring a section resyncs every Draft
            (views/questions), and so does saving Configure Default Batch - but CREATING one
            deliberately does not. Pushing a brand-new, empty section into a Draft would block
            that Draft from being finalized until somebody uploaded questions for it, which is
            the opposite of a safe default for a batch that was ready to send. */}
        <p>
          Existing batches won&apos;t change, Draft batches included. They keep the sections
          they were created with. A Draft picks this section up the next time the default batch
          settings are saved.
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

        <div className="alert amber" style={{ textAlign: 'left', marginTop: 4 }}>
          Add questions to this section before using it in a batch. A batch can&apos;t start an
          exam if a section doesn&apos;t have enough active questions.
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
