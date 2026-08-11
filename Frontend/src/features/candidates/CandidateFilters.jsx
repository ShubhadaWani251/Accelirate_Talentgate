// Shared filter box for any screen listing candidates (All Candidates, and the finalized-batch
// view of Batch Details). `showBatchFilter` is off inside Batch Details, where the batch is
// already fixed by the page itself.
export default function CandidateFilters({ filters, onChange, batches, onApply, onClear, showBatchFilter = true }) {
  function set(field, value) {
    onChange({ ...filters, [field]: value });
  }

  return (
    <div className="card" style={{ marginBottom: 16 }}>
      <div className="box-label">Filters</div>
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
          <label>Aadhaar</label>
          <input value={filters.aadhaar} onChange={(e) => set('aadhaar', e.target.value)} placeholder="Search Aadhaar…" />
        </div>
        {showBatchFilter && (
          <div className="field">
            <label>Batch Name</label>
            <select value={filters.batch_id} onChange={(e) => set('batch_id', e.target.value)}>
              <option value="">All Batches</option>
              {batches.map((b) => <option key={b.batch_id} value={b.batch_id}>{b.batch_name}</option>)}
            </select>
          </div>
        )}
      </div>
      <div className="grid-4" style={{ marginTop: 8 }}>
        <div className="field">
          <label>Result</label>
          <select value={filters.result} onChange={(e) => set('result', e.target.value)}>
            <option value="">All (Pass / Fail)</option>
            <option value="pass">Pass</option>
            <option value="fail">Fail</option>
            <option value="pending">Pending</option>
          </select>
        </div>
        <div className="field">
          <label>Overall Score — From</label>
          <input type="number" value={filters.score_min} onChange={(e) => set('score_min', e.target.value)} placeholder="e.g. 0" />
        </div>
        <div className="field">
          <label>Overall Score — To</label>
          <input type="number" value={filters.score_max} onChange={(e) => set('score_max', e.target.value)} placeholder="e.g. 40" />
        </div>
        <div className="field">
          <label>&nbsp;</label>
          <div className="btn-row" style={{ display: 'flex', gap: 10, marginTop: 0 }}>
            <button className="btn" onClick={onClear}>Clear Filters</button>
            <button className="btn primary" style={{ width: 'auto' }} onClick={onApply}>Apply Filters</button>
          </div>
        </div>
      </div>
    </div>
  );
}
