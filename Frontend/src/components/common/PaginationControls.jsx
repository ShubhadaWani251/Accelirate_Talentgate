// Matches api.pagination.StandardResultsPagination.page_size - the backend doesn't echo its own
// page size back in the list response, so this has to be kept in sync with that constant by hand.
const DEFAULT_PAGE_SIZE = 50;

// Which page-number buttons to show: always the first and last page, the current page and its
// immediate neighbours, with a '…' gap for anything skipped. Keeps the control usable at any
// list size - a 40-page candidate list gets "1 … 6 7 8 … 40", not forty buttons in a row.
function pageNumbers(current, total) {
  const pages = new Set([1, total, current - 1, current, current + 1]);
  return [...pages].filter((p) => p >= 1 && p <= total).sort((a, b) => a - b);
}

export default function PaginationControls({
  page, hasNext, hasPrevious, onPrev, onNext, onPageChange, count, pageSize = DEFAULT_PAGE_SIZE,
}) {
  if (!hasNext && !hasPrevious && (count == null || count === 0)) return null;

  const totalPages = Math.max(1, Math.ceil((count || 0) / pageSize));
  const numbers = pageNumbers(page, totalPages);

  return (
    <div className="btn-row" style={{
      display: 'flex', gap: 6, alignItems: 'center', justifyContent: 'flex-end',
      marginTop: 12, flexWrap: 'wrap',
    }}>
      {count != null && (
        <span style={{ fontSize: 12, color: 'var(--muted)', marginRight: 8 }}>{count} total</span>
      )}
      <button className="btn small" onClick={onPrev} disabled={!hasPrevious} aria-label="Previous page">
        ‹
      </button>
      {numbers.map((n, i) => (
        <span key={n} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {i > 0 && n - numbers[i - 1] > 1 && (
            <span style={{ fontSize: 12, color: 'var(--muted)' }}>…</span>
          )}
          <button
            type="button"
            className={`btn small${n === page ? ' primary' : ''}`}
            onClick={() => onPageChange?.(n)}
            disabled={n === page}
            aria-current={n === page ? 'page' : undefined}
          >
            {n}
          </button>
        </span>
      ))}
      <button className="btn small" onClick={onNext} disabled={!hasNext} aria-label="Next page">
        ›
      </button>
    </div>
  );
}
