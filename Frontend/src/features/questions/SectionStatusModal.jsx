import { useState } from 'react';
import toast from 'react-hot-toast';
import * as questionApi from '../../api/questionApi';
import { ButtonSpinner } from '../../components/loading/Spinner';
import { extractErrorMessage } from '../../utils/passwordSchema';

// Deactivate / Restore for one exam section - the same modal either way, because they are the
// two directions of one reversible switch, and which one is offered follows from the section's
// own state rather than from a choice the admin has to make.
//
// Deactivating never destroys anything: the section stops reaching NEW batches, and every batch
// that already ran it keeps it, along with every score recorded under it. That is why this can
// be a plain confirm rather than a type-the-name-to-confirm dialog - there is nothing here that
// a Restore cannot put back.
export default function SectionStatusModal({ section, onClose, onChanged }) {
  const [working, setWorking] = useState(false);

  async function run(action, successMessage) {
    setWorking(true);
    try {
      const message = await action();
      toast.success(message || successMessage);
      onChanged();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setWorking(false);
    }
  }

  const handleDeactivate = () => run(
    async () => (await questionApi.deleteSection(section.section_id)).detail,
    `"${section.section_name}" deactivated.`,
  );

  const handleRestore = () => run(
    async () => {
      await questionApi.setSectionActive(section.section_id, true);
      return `"${section.section_name}" is available to new batches again.`;
    },
  );

  if (!section.is_active) {
    return (
      <div className="modal-overlay" onClick={onClose}>
        <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 440 }}>
          <h4>Restore &quot;{section.section_name}&quot;?</h4>
          <p>
            New batches will include this section again. Its questions and every past result
            recorded under it are still exactly as they were — nothing was lost when it was
            deactivated.
          </p>
          {/* Draft batches follow the org defaults, so this reaches them immediately. Said out
              loud because it is the one thing restoring changes that the admin did not ask for
              directly. */}
          <div className="alert" style={{ textAlign: 'left' }}>
            Any <b>draft</b> batch will pick this section back up straight away. Batches already
            sent out are never reshaped.
          </div>
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
        <h4>Deactivate &quot;{section.section_name}&quot;?</h4>
        <p>
          This section will no longer be used in new batches. It will also be removed from any
          Draft batches.
        </p>
        {/* What is KEPT, as a list rather than a paragraph: these are three separate
            reassurances, and run together they read as one hedge nobody finishes. */}
        <div className="alert" style={{ textAlign: 'left' }}>
          <b>Nothing will be deleted.</b>
          <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
            <li>Batches that are no longer in Draft keep this section.</li>
            <li>Candidate scores for this section stay the same.</li>
            <li>Its questions stay in the question bank.</li>
          </ul>
        </div>
        <p style={{ fontSize: 12, color: 'var(--muted)' }}>
          You can turn this section back on anytime from <b>Inactive Sections</b>.
        </p>
        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 12 }}>
          <button className="btn" onClick={onClose} disabled={working}>Cancel</button>
          <button className="btn danger" onClick={handleDeactivate} disabled={working}>
            <ButtonSpinner loading={working}>Deactivate Section</ButtonSpinner>
          </button>
        </div>
      </div>
    </div>
  );
}
