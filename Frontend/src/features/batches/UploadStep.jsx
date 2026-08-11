import { useRef, useState } from 'react';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { extractErrorMessage } from '../../utils/passwordSchema';

export default function UploadStep({ batch, onUploaded }) {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
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
      onUploaded();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setUploading(false);
    }
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
        <button className="btn primary" style={{ width: 'auto' }} onClick={handleUpload} disabled={uploading}>
          {uploading ? 'Uploading…' : 'Review & Upload'}
        </button>
      </div>
    </div>
  );
}
