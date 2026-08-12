import { useState } from 'react';
import toast from 'react-hot-toast';
import * as questionApi from '../../api/questionApi';
import { extractErrorMessage } from '../../utils/passwordSchema';

export default function QuestionBulkUploadModal({ onClose, onUploaded }) {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);

  async function handleUpload() {
    if (!file) return;
    setUploading(true);
    setResult(null);
    try {
      const res = await questionApi.uploadQuestionsExcel(file);
      setResult(res);
      if (res.created_count > 0) onUploaded();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 460 }}>
        <h4>Bulk Upload Questions</h4>
        <p>Upload an .xlsx file matching the sample template - each valid row becomes an active question immediately.</p>

        <button className="link-text" style={{ marginBottom: 14 }} onClick={questionApi.downloadQuestionTemplate}>
          ⬇ Download Sample Template
        </button>

        <div className="field">
          <label>Question File (.xlsx)</label>
          <input type="file" accept=".xlsx" onChange={(e) => setFile(e.target.files[0] || null)} />
        </div>

        {result && (
          <div className={`alert ${result.error_count > 0 ? 'error' : 'success'}`}>
            {result.created_count} question(s) created
            {result.error_count > 0 && `, ${result.error_count} row(s) had errors:`}
            {result.error_count > 0 && (
              <ul style={{ margin: '6px 0 0', paddingLeft: 18 }}>
                {result.errors.slice(0, 10).map((e, i) => (
                  <li key={i}>Row {e.row}: {e.message}</li>
                ))}
                {result.errors.length > 10 && <li>…and {result.errors.length - 10} more</li>}
              </ul>
            )}
          </div>
        )}

        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose}>Close</button>
          <button className="btn primary" style={{ width: 'auto' }} onClick={handleUpload} disabled={!file || uploading}>
            {uploading ? 'Uploading…' : 'Upload'}
          </button>
        </div>
      </div>
    </div>
  );
}
