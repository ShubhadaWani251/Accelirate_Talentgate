import { useRef, useState } from 'react';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';

export default function UploadStep({ batch, onUploaded }) {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [headerWarning, setHeaderWarning] = useState(null);
  const inputRef = useRef(null);

  function handleDrop(e) {
    e.preventDefault();
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) setFile(dropped);
  }

  async function handleUpload() {
    if (!file) {
      toast.error('Choose a file first.');
      return;
    }
    setUploading(true);
    try {
      const result = await batchApi.uploadCandidates(batch.batch_id, file);
      toast.success(`${result.rows_created} row(s) uploaded (${result.ok_count} OK, ${result.validation_error_count} need attention).`);
      // Repeated entries collapse to one. Say so rather than leaving the reviewer to wonder
      // why a 40-row sheet became 38 candidates.
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
      onUploaded();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setUploading(false);
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
          <button className="btn primary" onClick={onUploaded}>
            Continue to Validation
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="card">
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
        <button className="btn primary" onClick={handleUpload} disabled={uploading}>
          <ButtonSpinner loading={uploading}>Review & Upload</ButtonSpinner>
        </button>
      </div>
    </div>
  );
}
