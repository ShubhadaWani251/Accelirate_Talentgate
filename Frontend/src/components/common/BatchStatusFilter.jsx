const OPTIONS = [
  { value: 'active', label: 'Active' },
  { value: 'draft', label: 'Draft' },
  { value: 'cancelled', label: 'Cancelled' },
  { value: 'all', label: 'All' },
];

// One unified Batch Status control, shared by the Dashboard and Batches list rather than each
// screen inventing its own toggle - "Active" means the same set of statuses (In Progress +
// Completed) everywhere, matching filter_batches_by_status_group on the backend.
export default function BatchStatusFilter({ value, onChange }) {
  return (
    <div className="btn-row" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
      <span style={{ fontSize: 12.5, color: 'var(--muted)', marginRight: 4 }}>Batch Status:</span>
      {OPTIONS.map((o) => (
        <button
          key={o.value}
          type="button"
          className={`btn small ${value === o.value ? 'primary' : ''}`}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
