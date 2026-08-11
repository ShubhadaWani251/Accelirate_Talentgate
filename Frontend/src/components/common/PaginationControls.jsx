// Minimal Previous/Next paging - enough to reach every row now that list endpoints are
// paginated, without building a full page-number picker the current data volumes don't need.
export default function PaginationControls({ page, hasNext, hasPrevious, onPrev, onNext, count }) {
  if (!hasNext && !hasPrevious && (count == null || count === 0)) return null;

  return (
    <div className="btn-row" style={{ display: 'flex', gap: 10, alignItems: 'center', justifyContent: 'flex-end', marginTop: 12 }}>
      {count != null && <span style={{ fontSize: 12, color: 'var(--muted)' }}>{count} total</span>}
      <button className="btn small" onClick={onPrev} disabled={!hasPrevious}>← Previous</button>
      <span style={{ fontSize: 12 }}>Page {page}</span>
      <button className="btn small" onClick={onNext} disabled={!hasNext}>Next →</button>
    </div>
  );
}
