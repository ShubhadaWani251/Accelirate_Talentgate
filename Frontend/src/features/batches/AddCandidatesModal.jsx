import { useRef, useState } from 'react';
import toast from 'react-hot-toast';
import * as batchApi from '../../api/batchApi';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';

// Adding candidates to a batch that is already live, as opposed to the upload wizard's own
// step (UploadStep.jsx) which only ever runs against a Draft.
//
// The important difference is what happens to a row that fails validation. The wizard has a
// whole Fix Errors step for those; here there is nowhere for them to go, so the server discards
// them and hands back the reasons. That result needs showing properly rather than as a toast -
// a TA who uploaded 40 rows and got 38 has to be able to see WHICH two, and why, to correct the
// spreadsheet. So the modal stays open on a partial success and renders the rejections.
export default function AddCandidatesModal({ batch, onClose, onAdded }) {
  const [file, setFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState(null);
  const uploadingRef = useRef(false);

  async function handleUpload() {
    if (uploadingRef.current) return;
    if (!file) {
      toast.error('Choose a .xlsx file first.');
      return;
    }
    uploadingRef.current = true;
    setUploading(true);
    try {
      const data = await batchApi.uploadCandidates(batch.batch_id, file);
      setResult(data);
      // Refresh the table underneath immediately - the new rows are already on the batch, so
      // leaving the modal open over a stale list would be misleading.
      onAdded();
      if (!data.rejected_count) {
        toast.success(data.detail);
        onClose();
      }
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      uploadingRef.current = false;
      setUploading(false);
    }
  }

  return (
    <div className="modal-overlay">
      <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 620 }}>
        <h4>Add Candidates to {batch.batch_name}</h4>

        {!result && (
          <>
            <p>
              Upload a spreadsheet to add more candidates to this running batch. It uses the same
              template as the original upload, and rows already on this batch are skipped
              automatically — so you can safely re-upload a corrected version of a file.
            </p>
            <p style={{ fontSize: 12.5, color: 'var(--muted)' }}>
              New candidates are added as <b>awaiting an invite</b>. They are not emailed
              automatically — select them in the table and use <b>Send New Invite Link</b> when
              you are ready. Rows that fail validation are not added; you will get the reasons
              back so you can correct them.
            </p>

            <div className="field">
              <label htmlFor="add_candidates_file">Candidate Spreadsheet (.xlsx)</label>
              <input
                id="add_candidates_file"
                type="file"
                accept=".xlsx"
                onChange={(e) => setFile(e.target.files?.[0] || null)}
              />
            </div>

            <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button className="btn" type="button" onClick={onClose}>Cancel</button>
              <button className="btn" type="button" onClick={() => batchApi.downloadTemplate()}>
                Download Template
              </button>
              <button className="btn primary" type="button" disabled={uploading}
                      onClick={handleUpload}>
                <ButtonSpinner loading={uploading}>Upload &amp; Add</ButtonSpinner>
              </button>
            </div>
          </>
        )}

        {result && (
          <>
            <div className={result.added_count ? 'alert' : 'alert error'}>{result.detail}</div>

            {Boolean(result.rejected?.length) && (
              <div className="field">
                <label>Rows not added ({result.rejected.length})</label>
                <div className="input-box filled"
                     style={{ maxHeight: 240, overflowY: 'auto', fontSize: 12.5 }}>
                  {result.rejected.map((row) => (
                    <div key={row.row_number} style={{ marginBottom: 10 }}>
                      <b>Row {row.row_number}</b>
                      {row.name ? ` — ${row.name}` : ''}
                      {row.email ? ` (${row.email})` : ''}
                      <ul style={{ margin: '4px 0 0 0', paddingLeft: 18 }}>
                        {row.errors.map((message) => (
                          <li key={message} style={{ color: 'var(--brand-red)' }}>{message}</li>
                        ))}
                      </ul>
                    </div>
                  ))}
                </div>
                <div className="field-hint">
                  Correct these rows in your spreadsheet and upload it again — the candidates
                  already added will be skipped as duplicates.
                </div>
              </div>
            )}

            <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button className="btn" type="button"
                      onClick={() => { setResult(null); setFile(null); }}>
                Upload Another File
              </button>
              <button className="btn primary" type="button" onClick={onClose}>Done</button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
