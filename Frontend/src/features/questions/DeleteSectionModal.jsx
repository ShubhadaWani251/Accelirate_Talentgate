import { useState } from 'react';
import toast from 'react-hot-toast';
import * as questionApi from '../../api/questionApi';
import { ButtonSpinner } from '../../components/loading/Spinner';
import { extractErrorMessage } from '../../utils/passwordSchema';

// One action, one meaning: the section stops appearing in any NEW batch, and everything that
// already used it stays exactly as it was.
//
// The server decides how to deliver that - a section nothing depends on is removed outright, one
// with questions or past batches behind it is retired instead, because a real delete would have
// to rewrite what a cohort was assessed on. That is an implementation detail of keeping the
// promise, not a choice to put in front of the admin, so this asks once and reports what
// happened afterwards.
export default function DeleteSectionModal({ section, onClose, onChanged }) {
  const [working, setWorking] = useState(false);

  async function handleDelete() {
    setWorking(true);
    try {
      const result = await questionApi.deleteSection(section.section_id);
      toast.success(result.detail);
      onChanged();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setWorking(false);
    }
  }

  async function handleRestore() {
    setWorking(true);
    try {
      await questionApi.setSectionActive(section.section_id, true);
      toast.success(`"${section.section_name}" is available to new batches again.`);
      onChanged();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setWorking(false);
    }
  }

  // Already deleted once. The only useful thing left to offer is putting it back.
  if (!section.is_active) {
    return (
      <div className="modal-overlay" onClick={onClose}>
        <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 440 }}>
          <h4>Restore &quot;{section.section_name}&quot;?</h4>
          <p>
            This section is already excluded from new batches. Restoring makes it available to
            them again; nothing about past batches changes either way.
          </p>
          <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 12 }}>
            <button className="btn" onClick={onClose} disabled={working}>Cancel</button>
            <button className="btn primary" onClick={handleRestore} disabled={working}>
              <ButtonSpinner loading={working}>Restore Section</ButtonSpinner>
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 440 }}>
        <h4>Delete &quot;{section.section_name}&quot;?</h4>
        <p>
          It will no longer appear in <b>new batches</b>, and will be removed from any draft
          batch that currently includes it.
        </p>
        <div className="alert" style={{ textAlign: 'left' }}>
          Batches that already ran this section keep it, and every candidate score recorded
          under it stays exactly as it is — their results still describe the exam they sat.
        </div>
        {section.in_use && (
          <p style={{ fontSize: 12, color: 'var(--muted)' }}>
            Its questions stay in the bank and remain visible on this screen, so you can still
            manage or move them.
          </p>
        )}
        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 12 }}>
          <button className="btn" onClick={onClose} disabled={working}>Cancel</button>
          <button className="btn danger" onClick={handleDelete} disabled={working}>
            <ButtonSpinner loading={working}>Delete Section</ButtonSpinner>
          </button>
        </div>
      </div>
    </div>
  );
}
