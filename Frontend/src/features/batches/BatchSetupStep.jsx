import { useEffect, useRef, useState } from 'react';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';
import UploadStep from './UploadStep';

// Step 1 of the wizard: name the batch and hand it a candidate file, on one screen and one
// button - a name with nothing uploaded against it, or an upload with nowhere to attach it,
// are both dead ends, so there is no reason to make them two separate pages.
//
// The exam schedule/question counts/cutoffs no longer belong here at all: they come from the
// admin-configured org-wide default (services/batch_defaults.py) and are snapshotted onto the
// batch the moment it's created (BatchListCreateView.post) - nothing on this screen can set or
// see them.
//
// `existingBatch` covers resuming a draft that already has a name but no candidates yet
// (BatchWizard sends a draft with total_candidates === 0 straight to this step) - there is
// nothing left to name, so that case renders the plain upload widget, unchanged.
export default function BatchSetupStep({ existingBatch, onCreated, onUploaded }) {
  const [batchName, setBatchName] = useState('');
  const [nameError, setNameError] = useState(null);
  // Set once creation succeeds, and never cleared afterward - a submit that fails at the upload
  // step (a bad file, a network blip) must retry the upload against this SAME batch, not create
  // a second one. This is also what silently drops the name input once it's no longer live.
  const [createdBatch, setCreatedBatch] = useState(existingBatch || null);
  const [file, setFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [headerWarning, setHeaderWarning] = useState(null);
  const inputRef = useRef(null);

  // Tells BatchWizard about the batch as soon as one exists, whichever way that happened - just
  // created here, or already existing because this is a resumed draft. FixErrorsStep/ReviewStep/
  // InviteConfirmationStep all read `batch` from the wizard's own state, not from here.
  useEffect(() => {
    if (createdBatch) onCreated(createdBatch);
  }, [createdBatch, onCreated]);

  // A resumed draft already has its name and candidate rows may already exist - nothing left to
  // combine, so this is exactly the old standalone upload screen.
  if (existingBatch) {
    return <UploadStep batch={existingBatch} onUploaded={onUploaded} />;
  }

  function handleDrop(e) {
    e.preventDefault();
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) setFile(dropped);
  }

  async function handleSubmit() {
    const name = batchName.trim();
    if (!createdBatch && !name) {
      setNameError('Batch name is required');
      return;
    }
    setNameError(null);
    if (!file) {
      toast.error('Choose a file first.');
      return;
    }

    setSubmitting(true);
    try {
      // Only created once - a retry after a failed upload reuses the batch this already made,
      // rather than leaving an abandoned empty one behind on every failed attempt.
      const batch = createdBatch || await batchApi.createBatch({ batch_name: name });
      if (!createdBatch) setCreatedBatch(batch);

      const result = await batchApi.uploadCandidates(batch.batch_id, file);
      toast.success(`${result.rows_created} row(s) uploaded (${result.ok_count} OK, ${result.validation_error_count} need attention).`);
      // Repeated entries collapse to one. Say so rather than leaving the reviewer to wonder why
      // a 40-row sheet became 38 candidates.
      if (result.skipped_duplicates?.length) {
        const n = result.skipped_duplicates.length;
        toast(`${n} repeated ${n === 1 ? 'entry' : 'entries'} skipped — only one row per `
              + 'candidate was kept.', { duration: 6000, icon: 'ℹ️' });
      }
      // A column the sheet doesn't carry imports as blank for every single row, which shows up
      // on the next screen as "every candidate is missing a name" rather than as one wrong
      // header cell. Hold here and name the columns instead of letting that happen silently.
      if (result.missing_columns?.length) {
        setHeaderWarning(result.missing_columns);
        return;
      }
      // Passed explicitly rather than letting BatchWizard's onUploaded close over its own
      // `batch` state - that closure is bound at BatchWizard's last render before this button
      // was clicked, which for a batch created in THIS same call is still null at that point.
      // The result was a silently-swallowed TypeError (caught, then ignored) immediately
      // followed by the step advancing anyway - "jumps to the next step" with nothing visibly
      // wrong. `batch` here is this function's own local, always current.
      onUploaded(batch);
    } catch (err) {
      toast.error(extractErrorMessage(err, ['batch_name']));
    } finally {
      setSubmitting(false);
    }
  }

  if (headerWarning) {
    return (
      <div className="card">
        <div className="box-label">Check the column headers</div>
        <div className="alert error">
          This sheet has no column for <b>{headerWarning.join(', ')}</b>, so every row was
          imported with {headerWarning.length > 1 ? 'those fields' : 'that field'} blank.
          <div style={{ marginTop: 8 }}>
            Rename the header row to match the template and upload it again, or continue and
            fill the missing values in row by row on the next screen.
          </div>
        </div>
        <div className="btn-row" style={{ display: 'flex', gap: 10, marginTop: 14 }}>
          <button
            type="button"
            className="btn"
            onClick={() => batchApi.downloadTemplate().catch(() => toast.error('Could not download the template.'))}
          >
            ⬇ Download Template
          </button>
          {/* createdBatch, not a stale outer closure - it's component state, guaranteed to
              already reflect the batch this upload just landed on by the time this renders. */}
          <button className="btn primary" onClick={() => onUploaded(createdBatch)}>
            Continue to Validation
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="card">
      <div className="box-label">Batch Details</div>
      <div className="field" style={{ maxWidth: 420, marginBottom: 16 }}>
        <label htmlFor="batch_name">Batch Name</label>
        <input
          id="batch_name"
          className={nameError ? 'has-error' : ''}
          value={batchName}
          onChange={(e) => setBatchName(e.target.value)}
          // Locked once the batch exists - renaming afterward belongs on the batch's own
          // Details page, not this one-time setup screen.
          disabled={!!createdBatch}
        />
        {nameError && <div className="field-error">{nameError}</div>}
      </div>

      <div className="box-label">Upload Excel File</div>
      <div
        className="dropzone"
        onClick={() => inputRef.current?.click()}
        onDragOver={(e) => e.preventDefault()}
        onDrop={handleDrop}
      >
        {file ? (
          <span>Selected: <strong>{file.name}</strong></span>
        ) : (
          <span>Drag file here or click to browse — candidate_upload_template.xlsx</span>
        )}
        <input
          ref={inputRef}
          type="file"
          accept=".xlsx"
          style={{ display: 'none' }}
          onChange={(e) => setFile(e.target.files?.[0] || null)}
        />
      </div>

      <div className="btn-row" style={{ display: 'flex', gap: 10, marginTop: 14 }}>
        <button
          type="button"
          className="btn"
          onClick={() => batchApi.downloadTemplate().catch(() => toast.error('Could not download the template.'))}
        >
          ⬇ Download Template
        </button>
        <button type="button" className="btn primary" onClick={handleSubmit} disabled={submitting}>
          <ButtonSpinner loading={submitting}>Create Batch &amp; Upload</ButtonSpinner>
        </button>
      </div>
    </div>
  );
}
