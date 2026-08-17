import { useRef, useState } from 'react';
import toast from 'react-hot-toast';
import * as questionApi from '../../api/questionApi';
import QuestionValidationRow from './QuestionValidationRow';
import { extractErrorMessage } from '../../utils/passwordSchema';

// Two-phase: validate first, show every row and what's wrong with it, and only then import.
// Nothing reaches the database until the administrator has reviewed the results and pressed
// Import - and the import re-validates server-side rather than trusting this screen.
//
// Rows can be corrected in place: an edited row is sent back for revalidation, so a bad section
// name or correct-answer letter is fixed here rather than by editing the spreadsheet and
// re-uploading. Once anything has been edited, the import posts the edited rows rather than
// re-reading the original file.
export default function QuestionBulkUploadModal({ sections = [], onClose, onUploaded }) {
  const [file, setFile] = useState(null);
  const [validating, setValidating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [validation, setValidation] = useState(null);  // { summary, rows, by_section }
  const [result, setResult] = useState(null);
  const [edited, setEdited] = useState(false);
  const importingRef = useRef(false);

  // Revalidate the whole set after an edit: one row's correction can change another's verdict
  // (fixing a typo can turn a later row into a duplicate of it), so counts are only right when
  // every row is re-checked together.
  async function handleRowSave(updatedRow) {
    const rows = validation.rows.map((r) =>
      r.row_number === updatedRow.row_number ? { ...r, ...updatedRow } : r);
    setValidating(true);
    try {
      setValidation(await questionApi.validateQuestionRows(rows));
      setEdited(true);
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setValidating(false);
    }
  }

  async function handleValidate() {
    if (!file) return;
    setValidating(true);
    setValidation(null);
    setResult(null);
    try {
      setValidation(await questionApi.validateQuestionsExcel(file));
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setValidating(false);
    }
  }

  async function handleImport() {
    if (importingRef.current) return;
    importingRef.current = true;
    setImporting(true);
    try {
      // Once rows have been corrected here, the file on disk no longer reflects what the
      // reviewer approved - import the edited rows instead of re-reading it.
      const res = edited
        ? await questionApi.importQuestionRows(validation.rows)
        : await questionApi.importQuestionsExcel(file);
      setResult(res);
      if (res.created_count > 0) onUploaded();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      importingRef.current = false;
      setImporting(false);
    }
  }

  function reset() {
    setFile(null);
    setValidation(null);
    setResult(null);
  }

  const summary = validation?.summary;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}
           style={{ maxWidth: validation ? 900 : 460 }}>
        <h4>{validation ? 'Question Validation' : 'Bulk Upload Questions'}</h4>

        {!validation && (
          <>
            <p>
              Upload an .xlsx file matching the sample template. Questions are validated first —
              nothing is imported until you review the results.
            </p>
            <div className="alert" style={{ marginBottom: 14 }}>
              One sheet can hold questions for several sections. Each row is filed into whatever
              its own <b>Section</b> column names.
            </div>
            <button className="link-text" style={{ marginBottom: 14 }}
                    onClick={questionApi.downloadQuestionTemplate}>
              ⬇ Download Sample Template
            </button>
            <div className="field">
              <label>Question File (.xlsx)</label>
              <input type="file" accept=".xlsx" onChange={(e) => setFile(e.target.files[0] || null)} />
            </div>
          </>
        )}

        {summary && !result && (
          <>
            <div className="grid-4" style={{ marginBottom: 14 }}>
              <div className="stat-card"><div className="stat-num">{summary.total}</div><div className="stat-lbl">Total Questions</div></div>
              <div className="stat-card"><div className="stat-num">{summary.valid}</div><div className="stat-lbl">Valid</div></div>
              <div className="stat-card"><div className="stat-num">{summary.invalid}</div><div className="stat-lbl">Invalid</div></div>
              <div className="stat-card"><div className="stat-num">{summary.duplicate}</div><div className="stat-lbl">Duplicate</div></div>
            </div>

            {Object.keys(validation.by_section).length > 0 && (
              <div className="alert" style={{ marginBottom: 12 }}>
                Valid questions will be filed as:{' '}
                {Object.entries(validation.by_section)
                  .map(([name, n]) => `${name} (${n})`).join(' · ')}
              </div>
            )}

            {summary.valid === 0 && (
              <div className="alert error">
                No valid questions to import. Correct the file and upload it again.
              </div>
            )}

            <div className="table-scroll" style={{ maxHeight: 320 }}>
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Row</th><th>Section</th><th>Question</th><th>Type</th>
                    <th>Correct</th><th>Marks</th><th>Status</th><th>Error</th><th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {validation.rows.map((r) => (
                    <QuestionValidationRow
                      key={r.row_number}
                      row={r}
                      sections={sections}
                      onSave={handleRowSave}
                      saving={validating}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}

        {result && (
          <div className={`alert ${result.created_count > 0 ? 'success' : 'error'}`}>
            Imported {result.created_count} question(s).
            {result.summary.invalid > 0 && ` ${result.summary.invalid} invalid row(s) were skipped.`}
            {result.summary.duplicate > 0 && ` ${result.summary.duplicate} duplicate(s) were skipped.`}
          </div>
        )}

        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 14 }}>
          <button className="btn" onClick={onClose}>Close</button>
          {validation && !result && (
            <button className="btn" onClick={reset}>← Back / Re-upload</button>
          )}
          {!validation && (
            <button className="btn primary" style={{ width: 'auto' }} onClick={handleValidate}
                    disabled={!file || validating}>
              {validating ? 'Validating…' : 'Validate'}
            </button>
          )}
          {validation && !result && (
            <button className="btn primary" style={{ width: 'auto' }} onClick={handleImport}
                    disabled={summary.valid === 0 || importing}>
              {importing ? 'Importing…' : `Import ${summary.valid} Question(s)`}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
