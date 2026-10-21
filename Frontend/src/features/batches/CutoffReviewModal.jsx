import { ButtonSpinner } from '../../components/loading/Spinner';

// Review step between editing a batch's cutoffs and applying them. Changing a cutoff re-grades
// everyone who has already sat the exam, and before this the only way to see what that did was
// to do it and read the pass/fail columns afterwards.
//
// `preview` is the server's answer (features/../api/batchApi.previewBatchCutoffs): the real
// regrade, run inside a transaction and rolled back, so what this shows and what Apply does
// cannot disagree.

const BAND_LABEL = { pass: 'Pass', fail: 'Fail', borderline: 'Borderline', pending: 'Not yet sat' };
const BAND_TONE = { pass: 'green', fail: 'red', borderline: 'amber', pending: 'gray' };
// Pending last: it is the one band that says nothing about the cutoff being reviewed.
const BAND_ORDER = ['pass', 'fail', 'borderline', 'pending'];

function Delta({ from, to }) {
  const diff = to - from;
  if (diff === 0) return <span style={{ color: 'var(--muted)' }}>no change</span>;
  return (
    <span style={{ color: diff > 0 ? 'var(--brand-green, #1a7f37)' : 'var(--brand-red)' }}>
      {diff > 0 ? '+' : ''}{diff}
    </span>
  );
}

export default function CutoffReviewModal({ preview, applying, onApply, onClose }) {
  const {
    cutoff_changes: cutoffChanges = [],
    before = {}, after = {},
    changed = [], changed_count: changedCount = 0,
    changed_truncated: truncated = 0,
    graded_candidates: gradedCandidates = 0,
    decided_by_hand: decidedByHand = 0,
  } = preview || {};

  const nothingChanges = cutoffChanges.length === 0;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-box" style={{ maxWidth: 620 }} onClick={(e) => e.stopPropagation()}>
        <h4>Review cutoff changes</h4>

        {nothingChanges ? (
          <p>These cutoffs match what the batch already has — there is nothing to apply.</p>
        ) : (
          <>
            <p>
              {gradedCandidates === 0
                ? 'Nobody in this batch has sat the exam yet, so no results change today. '
                  + 'The new cutoffs will apply as candidates finish.'
                : `Re-grading ${gradedCandidates} candidate(s) who have already sat the exam.`}
            </p>

            <div className="field">
              <label>Cutoffs</label>
              <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5 }}>
                {cutoffChanges.map((c) => (
                  <li key={c.section_key}>
                    <b>{c.section_name}</b>: {c.from}% → {c.to}%
                  </li>
                ))}
              </ul>
            </div>

            <div className="field">
              <label>Results</label>
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr><th>Band</th><th>Now</th><th>After</th><th>Change</th></tr>
                  </thead>
                  <tbody>
                    {BAND_ORDER.filter((b) => (before[b] || 0) + (after[b] || 0) > 0).map((b) => (
                      <tr key={b}>
                        <td><span className={`pill ${BAND_TONE[b]}`}>{BAND_LABEL[b]}</span></td>
                        <td>{before[b] || 0}</td>
                        <td>{after[b] || 0}</td>
                        <td><Delta from={before[b] || 0} to={after[b] || 0} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            {changedCount > 0 && (
              <div className="field">
                <label>{changedCount} candidate(s) move</label>
                <ul style={{ margin: 0, paddingLeft: 18, fontSize: 12.5 }}>
                  {changed.map((c) => (
                    <li key={c.candidate_id}>
                      {c.name}: {BAND_LABEL[c.from] || c.from} → <b>{BAND_LABEL[c.to] || c.to}</b>
                    </li>
                  ))}
                </ul>
                {truncated > 0 && (
                  <p style={{ fontSize: 12, color: 'var(--muted)', margin: '6px 0 0' }}>
                    …and {truncated} more.
                  </p>
                )}
              </div>
            )}

            {/* Named rather than left to be discovered: a reviewer who expects these to move
                would otherwise read the whole preview as wrong. */}
            {decidedByHand > 0 && (
              <p className="export-scope">
                {decidedByHand} borderline result(s) were decided by hand and stay as they are,
                whatever the cutoff does.
              </p>
            )}
          </>
        )}

        <div className="btn-row" style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <button className="btn" onClick={onClose}>
            {nothingChanges ? 'Close' : 'Back to editing'}
          </button>
          {!nothingChanges && (
            <button className="btn primary" onClick={onApply} disabled={applying}>
              <ButtonSpinner loading={applying}>Apply cutoffs</ButtonSpinner>
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
