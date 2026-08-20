import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import toast from 'react-hot-toast';
import * as questionApi from '../../api/questionApi';
import QuestionValidationRow from '../../features/questions/QuestionValidationRow';
import { extractErrorMessage } from '../../utils/passwordSchema';
import { ButtonSpinner } from '../../components/loading/Spinner';

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

  // Revalidate the whole set after any change: one row's correction can change another's
  // verdict (fixing a typo can turn a later row into a duplicate of it, and removing one of a
  // duplicate pair makes its twin valid), so counts are only right when every remaining row is
  // re-checked together.
  async function revalidate(rows) {
    if (rows.length === 0) {
      // Nothing left to check - the validate-rows endpoint rejects an empty list, and there's
      // no server round-trip worth making for it.
      setValidation({ summary: { total: 0, valid: 0, invalid: 0, duplicate: 0 },
                      rows: [], by_section: {} });
      setEdited(true);
      return;
    }
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

  function handleRowSave(updatedRow) {
    return revalidate(validation.rows.map((r) =>
      r.row_number === updatedRow.row_number ? { ...r, ...updatedRow } : r));
  }

  // Dropping a row affects this upload only - nothing has reached the bank yet, so there is no
  // database record to delete.
  function handleRowRemove(row) {
    return revalidate(validation.rows.filter((r) => r.row_number !== row.row_number));
  }

  function handleRemoveAllProblem() {
    const keep = validation.rows.filter((r) => r.status === 'valid');
    const dropped = validation.rows.length - keep.length;
    revalidate(keep);
    toast.success(`Removed ${dropped} row(s) that could not be imported.`);
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
        <Link to="/admin/question-bank" className="btn">
          ← Back to Question Bank
        </Link>
      </div>

      {/* Import outcome is a dialog, not another full screen: it's a short confirmation with two
          exits, and showing it as a page left the reviewer looking at an almost-empty layout. */}
      {result && (
        <div className="modal-overlay" onClick={() => navigate('/admin/question-bank')}>
          <div className="modal-box" onClick={(e) => e.stopPropagation()} style={{ maxWidth: 440 }}>
            <h4>{result.created_count > 0 ? 'Import Complete' : 'Nothing Imported'}</h4>
            <div className={`alert ${result.created_count > 0 ? 'success' : 'error'}`}>
              Imported <b>{result.created_count}</b> question(s).
              {result.summary.invalid > 0 && ` ${result.summary.invalid} invalid row(s) were skipped.`}
              {result.summary.duplicate > 0 && ` ${result.summary.duplicate} duplicate(s) were skipped.`}
            </div>
            {Object.keys(result.by_section || {}).length > 0 && (
              <div className="field">
                <label>Filed as</label>
                <div style={{ fontSize: 12.5 }}>
                  {Object.entries(result.by_section)
                    .map(([name, n]) => `${name} (${n})`).join(' · ')}
                </div>
              </div>
            )}
            <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <button className="btn" onClick={reset}>Upload Another File</button>
              <button className="btn primary"
                      onClick={() => navigate('/admin/question-bank')}>
                Done — View Question Bank
              </button>
            </div>
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
            <b>One sheet per section.</b> Each sheet&apos;s name decides where its questions are
            filed — put programming questions on the <b>Programming</b> sheet and so on. The
            downloadable template already has a sheet for every section.
            <div style={{ marginTop: 6, color: 'var(--muted)' }}>
              Older files still work: a sheet carrying its own <b>Section</b> column is filed
              row by row from that column instead.
            </div>
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
            <button className="btn primary" onClick={handleValidate}
                    disabled={!file || validating}>
              <ButtonSpinner loading={validating}>Validate</ButtonSpinner>
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

          {summary.total > 0 && summary.valid === 0 && (
            <div className="alert error">
              {summary.duplicate === summary.total
                ? 'Every question in this file is already in the bank, so there is nothing new to '
                  + 'import. This usually means the file has been uploaded before. Use Edit to '
                  + 'reword a question if you meant to add a variation of it.'
                : 'No valid questions to import. Use Edit on a row to correct it — it is '
                  + 're-checked as soon as you save.'}
            </div>
          )}

          {/* Clears the rows that can't be imported in one go, so a file where most rows are
              duplicates doesn't have to be pruned one Remove at a time. */}
          {summary.total > summary.valid && (
            <div className="btn-row" style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
              <button className="btn danger" onClick={handleRemoveAllProblem} disabled={validating}>
                Remove all {summary.total - summary.valid} row(s) that can&apos;t be imported
              </button>
            </div>
          )}

          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Sheet · Row</th><th>Section</th><th>Question</th><th>Type</th>
                  <th>Correct</th><th>Marks</th><th>Status</th><th>Error</th><th>Action</th>
                </tr>
              </thead>
              <tbody>
                {validation.rows.length === 0 ? (
                  <tr><td colSpan={9}>
                    Every row has been removed. Go back and upload a file to start again.
                  </td></tr>
                ) : validation.rows.map((r) => (
                  <QuestionValidationRow
                    key={r.row_number}
                    row={r}
                    sections={sections}
                    onSave={handleRowSave}
                    onRemove={handleRowRemove}
                    saving={validating}
                  />
                ))}
              </tbody>
            </table>
          </div>

          <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 14 }}>
            <button className="btn" onClick={reset}>← Back / Re-upload</button>
            <button className="btn primary" onClick={handleImport}
                    disabled={summary.valid === 0 || importing}>
              {importing ? 'Importing…' : `Import ${summary.valid} Question(s)`}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
