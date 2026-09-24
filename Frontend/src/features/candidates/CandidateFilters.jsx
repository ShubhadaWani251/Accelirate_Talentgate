// Shared filter box for any screen listing candidates (All Candidates, and the finalized-batch
// view of Batch Details). `showBatchFilter` is off inside Batch Details, where the batch is
// already fixed by the page itself.

// Section score ranges map 1:1 onto the backend's <section>_min / <section>_max query params.
//
// `sections` comes from the caller rather than a fixed list of four. It used to be hardcoded,
// which left this box disagreeing with the table beside it the moment sections became something
// an admin manages: a section added from Question Bank Management got a score COLUMN but no way
// to filter on it, and a retired one kept a filter that could no longer match anything.
//
// All Candidates passes every section that exists (it lists people from different batches side
// by side); Batch Details passes that batch's own, which is also the only set its rows can have
// a score in.
export default function CandidateFilters({
  filters, onChange, batches, onApply, onClear, showBatchFilter = true, sections = [],
}) {
  function set(field, value) {
    onChange({ ...filters, [field]: value });
  }

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="box-label">{showBatchFilter ? 'Filters' : 'Filters — within this batch'}</div>
      <div className="grid-4">
        <div className="field">
          <label>Name</label>
          <input value={filters.name} onChange={(e) => set('name', e.target.value)} placeholder="Search name…" />
        </div>
        <div className="field">
          <label>Email</label>
          <input value={filters.email} onChange={(e) => set('email', e.target.value)} placeholder="Search email…" />
        </div>
        <div className="field">
          <label>Aadhaar Last 4 Digits</label>
          <input value={filters.aadhaar} onChange={(e) => set('aadhaar', e.target.value)} placeholder="Last 4 digits…" maxLength={4} />
        </div>
        {showBatchFilter ? (
          <div className="field">
            <label>Batch Name</label>
            <select value={filters.batch_id} onChange={(e) => set('batch_id', e.target.value)}>
              <option value="">All Batches</option>
              {batches.map((b) => <option key={b.batch_id} value={b.batch_id}>{b.batch_name}</option>)}
            </select>
          </div>
        ) : (
          <div className="field">
            <label>Result</label>
            <select value={filters.result} onChange={(e) => set('result', e.target.value)}>
              <option value="">All Results</option>
              <option value="pass">Pass</option>
              <option value="fail">Fail</option>
              {/* The Borderline card on Batch Details is a work queue - this is how a TA
                  actually gets to the people sitting in it. */}
              <option value="borderline">Borderline</option>
              <option value="pending">Pending</option>
            </select>
          </div>
        )}
      </div>

      <div className="grid-4" style={{ marginTop: 8 }}>
        {showBatchFilter && (
          <div className="field">
            <label>Result</label>
            <select value={filters.result} onChange={(e) => set('result', e.target.value)}>
              <option value="">All Results</option>
              <option value="pass">Pass</option>
              <option value="fail">Fail</option>
              <option value="borderline">Borderline</option>
              <option value="pending">Pending</option>
            </select>
          </div>
        )}
        <div className="field">
          <label>Overall Score — From</label>
          <input type="number" value={filters.score_min} onChange={(e) => set('score_min', e.target.value)} placeholder="e.g. 0" />
        </div>
        <div className="field">
          <label>Overall Score — To</label>
          <input type="number" value={filters.score_max} onChange={(e) => set('score_max', e.target.value)} placeholder="e.g. 40" />
        </div>
      </div>

      {/* Hidden entirely when there are no sections, rather than rendering a heading over an
          empty grid - which is what a brand-new deployment, or a batch whose sections were all
          retired, would otherwise show. */}
      {sections.length > 0 && (
        <>
          <div className="box-label" style={{ marginTop: 14 }}>Section-wise Score</div>
          <div className="grid-4">
            {sections.map((s) => (
              <div className="field" key={s.section_key}>
                <label>{s.section_name} — From / To</label>
                <div style={{ display: 'flex', gap: 6 }}>
                  {/* ?? '' because these keys are no longer in a fixed blank-filter object -
                      a section added since the page loaded has no entry until it is typed in,
                      and undefined here would make the input uncontrolled. */}
                  <input type="number" placeholder="From"
                    value={filters[`${s.section_key}_min`] ?? ''}
                    onChange={(e) => set(`${s.section_key}_min`, e.target.value)} />
                  <input type="number" placeholder="To"
                    value={filters[`${s.section_key}_max`] ?? ''}
                    onChange={(e) => set(`${s.section_key}_max`, e.target.value)} />
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      <div className="btn-row" style={{ display: 'flex', gap: 10, marginTop: 12 }}>
        <button className="btn" onClick={onClear}>Clear Filters</button>
        <button className="btn primary" onClick={onApply}>Apply Filters</button>
      </div>
    </div>
  );
}
