// Shared filter box for any screen listing candidates (All Candidates, and the finalized-batch
// view of Batch Details). `showBatchFilter` is off inside Batch Details, where the batch is
// already fixed by the page itself.

// Section score ranges map 1:1 onto the backend's <section>_min / <section>_max query params.
const SECTIONS = [
  { key: 'logical', label: 'Logical' },
  { key: 'quantitative', label: 'Quant.' },
  { key: 'verbal', label: 'Verbal' },
  { key: 'programming', label: 'Programming' },
];

export default function CandidateFilters({ filters, onChange, batches, onApply, onClear, showBatchFilter = true }) {
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
              <option value="">All (Pass / Fail)</option>
              <option value="pass">Pass</option>
              <option value="fail">Fail</option>
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
              <option value="">All (Pass / Fail)</option>
              <option value="pass">Pass</option>
              <option value="fail">Fail</option>
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

      <div className="box-label" style={{ marginTop: 14 }}>Section-wise Score</div>
      <div className="grid-4">
        {SECTIONS.map((s) => (
          <div className="field" key={s.key}>
            <label>{s.label} — From / To</label>
            <div style={{ display: 'flex', gap: 6 }}>
              <input type="number" placeholder="From" value={filters[`${s.key}_min`]}
                onChange={(e) => set(`${s.key}_min`, e.target.value)} />
              <input type="number" placeholder="To" value={filters[`${s.key}_max`]}
                onChange={(e) => set(`${s.key}_max`, e.target.value)} />
            </div>
          </div>
        ))}
      </div>

      <div className="btn-row" style={{ display: 'flex', gap: 10, marginTop: 12 }}>
        <button className="btn" onClick={onClear}>Clear Filters</button>
        <button className="btn primary" onClick={onApply}>Apply Filters</button>
      </div>
    </div>
  );
}
