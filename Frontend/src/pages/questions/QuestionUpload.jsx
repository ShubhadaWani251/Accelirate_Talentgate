import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import * as questionApi from '../../api/questionApi';
import QuestionValidationRow from '../../features/questions/QuestionValidationRow';
import { extractErrorMessage } from '../../utils/passwordSchema';

// Full page rather than a modal: the validation table is 9 columns wide and every row can
// expand into an edit form, which inside a fixed-height dialog meant three nested scrollbars
// and a question column too narrow to read.
//
// Two-phase: validate first, show every row and what's wrong with it, and only then import.
// Nothing reaches the database until the administrator has reviewed the results and pressed
// Import - and the import re-validates server-side rather than trusting this screen.
//
// Rows can be corrected in place: an edited row is sent back for revalidation, so a bad section
// name or correct-answer letter is fixed here rather than by editing the spreadsheet and
// re-uploading. Once anything has been edited, the import posts the edited rows rather than
// re-reading the original file.
export default function QuestionUpload() {
  const navigate = useNavigate();
  const [sections, setSections] = useState([]);
  const [file, setFile] = useState(null);
  const [validating, setValidating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [validation, setValidation] = useState(null);  // { summary, rows, by_section }
  const [result, setResult] = useState(null);
  const [edited, setEdited] = useState(false);
  const importingRef = useRef(false);
  const inputRef = useRef(null);

  useEffect(() => {
    questionApi.getSections().then(setSections)
      .catch((err) => toast.error(extractErrorMessage(err)));
  }, []);

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
    if (!file) {
      toast.error('Choose a file first.');
      return;
    }
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
    setEdited(false);
  }

  function handleDrop(e) {
    e.preventDefault();
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) setFile(dropped);
  }

  const summary = validation?.summary;

  return (
    <div className="page-wide">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                   flexWrap: 'wrap', gap: 10 }}>
        <h3>{validation ? 'Question Validation' : 'Bulk Upload Questions'}</h3>
        <Link to="/admin/question-bank" className="btn" style={{ width: 'auto', textDecoration: 'none' }}>
          ← Back to Question Bank
        </Link>
      </div>

      {result && (
        <div className={`alert ${result.created_count > 0 ? 'success' : 'error'}`}>
          Imported {result.created_count} question(s).
          {result.summary.invalid > 0 && ` ${result.summary.invalid} invalid row(s) were skipped.`}
          {result.summary.duplicate > 0 && ` ${result.summary.duplicate} duplicate(s) were skipped.`}
          <div className="btn-row" style={{ display: 'flex', gap: 10, marginTop: 12 }}>
            <button className="btn" onClick={reset}>Upload Another File</button>
            <button className="btn primary" style={{ width: 'auto' }}
                    onClick={() => navigate('/admin/question-bank')}>
              Done — View Question Bank
            </button>
          </div>
        </div>
      )}

      {!validation && !result && (
        <div className="card">
          <div className="box-label">Upload Excel File</div>
          <p>
            Upload an .xlsx file matching the sample template. Questions are validated first —
            nothing is imported until you review the results.
          </p>
          <div className="alert" style={{ marginBottom: 14 }}>
            One sheet can hold questions for several sections. Each row is filed into whatever
            its own <b>Section</b> column names.
          </div>

          <div
            className="dropzone"
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={handleDrop}
          >
            {file ? (
              <span>Selected: <strong>{file.name}</strong></span>
            ) : (
              <span>Drag file here or click to browse — question_upload_template.xlsx</span>
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
            <button className="btn" onClick={questionApi.downloadQuestionTemplate}>
              ⬇ Download Sample Template
            </button>
            <button className="btn primary" style={{ width: 'auto' }} onClick={handleValidate}
                    disabled={!file || validating}>
              {validating ? 'Validating…' : 'Validate'}
            </button>
          </div>
        </div>
      )}

      {summary && !result && (
        <div className="card">
          <div className="grid-4" style={{ marginBottom: 14 }}>
            <div className="stat-card"><div className="stat-num">{summary.total}</div><div className="stat-lbl">Total Questions</div></div>
            <div className="stat-card">
              <div className="stat-num" style={{ color: summary.valid ? 'var(--green)' : undefined }}>{summary.valid}</div>
              <div className="stat-lbl">Valid</div>
            </div>
            <div className="stat-card">
              <div className="stat-num" style={{ color: summary.invalid ? 'var(--red)' : undefined }}>{summary.invalid}</div>
              <div className="stat-lbl">Invalid</div>
            </div>
            <div className="stat-card">
              <div className="stat-num" style={{ color: summary.duplicate ? 'var(--amber)' : undefined }}>{summary.duplicate}</div>
              <div className="stat-lbl">Duplicate</div>
            </div>
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
              {summary.duplicate === summary.total
                ? 'Every question in this file is already in the bank, so there is nothing new to '
                  + 'import. This usually means the file has been uploaded before. Use Edit to '
                  + 'reword a question if you meant to add a variation of it.'
                : 'No valid questions to import. Use Edit on a row to correct it — it is '
                  + 're-checked as soon as you save.'}
            </div>
          )}

          <div className="table-scroll">
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

          <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 14 }}>
            <button className="btn" onClick={reset}>← Back / Re-upload</button>
            <button className="btn primary" style={{ width: 'auto' }} onClick={handleImport}
                    disabled={summary.valid === 0 || importing}>
              {importing ? 'Importing…' : `Import ${summary.valid} Question(s)`}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
