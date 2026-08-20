/**
 * Skeleton loading primitives.
 *
 * Accessibility approach: the individual bars are decorative and marked aria-hidden, while the
 * WRAPPER carries role="status" + aria-busy. A screen reader therefore announces "Loading…" once
 * per region instead of reading out dozens of meaningless boxes. Wrap composed skeletons in
 * <SkeletonRegion> (or pass `region` to the composed components below) exactly once.
 *
 * Styling lives in styles/theme.css (.skeleton*) so the shimmer is one lightweight CSS animation
 * reused everywhere, with no animation library and no per-element inline keyframes.
 */

/** Announce-once wrapper. Everything inside it is hidden from assistive tech. */
export function SkeletonRegion({ label = 'Loading…', children, className = '', style }) {
  return (
    <div
      className={className}
      style={style}
      role="status"
      aria-busy="true"
      aria-live="polite"
      aria-label={label}
    >
      <span className="sr-only">{label}</span>
      <div aria-hidden="true">{children}</div>
    </div>
  );
}

/** Base block. `width`/`height` accept any CSS length; `radius` defaults to the app's 8px. */
export function Skeleton({ width = '100%', height = 12, radius = 8, className = '', style }) {
  return (
    <span
      className={`skeleton ${className}`}
      style={{ width, height, borderRadius: radius, ...style }}
    />
  );
}

/**
 * Several lines of faux text. The last line is deliberately shorter so it reads as a paragraph
 * rather than a solid block.
 */
export function SkeletonText({ lines = 3, width = '100%', lastLineWidth = '60%', gap = 8, height = 12 }) {
  return (
    <span className="skeleton-stack" style={{ gap }}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          height={height}
          width={i === lines - 1 && lines > 1 ? lastLineWidth : width}
        />
      ))}
    </span>
  );
}

/* No SkeletonCircle here on purpose: nothing circular in this app loads asynchronously (the nav
   avatar renders from the Redux session, not a request), so it would have been dead code. Add one
   if an async avatar/image ever appears. */

/** Matches the app's `.card` shape so swapping to real content doesn't shift the layout. */
export function SkeletonCard({ lines = 3, showLabel = true, style }) {
  return (
    <div className="card" style={style}>
      {showLabel && <Skeleton width="38%" height={11} style={{ marginBottom: 14 }} />}
      <SkeletonText lines={lines} />
    </div>
  );
}

/** Mirrors a `.stat-card` from the dashboard's grid. */
export function SkeletonStatCard() {
  return (
    <div className="stat-card">
      <Skeleton width="44%" height={22} style={{ margin: '0 auto' }} />
      <Skeleton width="70%" height={10} style={{ margin: '8px auto 0' }} />
    </div>
  );
}

/**
 * Rows for an existing `.data-table`. Rendered as real <tr>/<td> so it sits inside the actual
 * table and inherits its column widths - a separate overlay would not line up.
 *
 * Used INSIDE a <tbody>, so it can't carry its own role="status" wrapper (invalid table markup);
 * the surrounding `.table-scroll` gets aria-busy instead - see SkeletonTable.
 */
export function SkeletonTableRows({ rows = 5, columns = 6 }) {
  return Array.from({ length: rows }).map((_, r) => (
    <tr key={r} aria-hidden="true">
      {Array.from({ length: columns }).map((__, c) => (
        <td key={c}>
          <Skeleton height={11} width={c === 0 ? '80%' : '60%'} />
        </td>
      ))}
    </tr>
  ));
}

/** Standalone table skeleton, including its header, for when the real table isn't rendered yet. */
export function SkeletonTable({ rows = 5, columns = 6, label = 'Loading table…' }) {
  return (
    <div className="table-scroll" role="status" aria-busy="true" aria-label={label}>
      <span className="sr-only">{label}</span>
      <table className="data-table">
        <thead aria-hidden="true">
          <tr>
            {Array.from({ length: columns }).map((_, c) => (
              <th key={c}><Skeleton height={10} width="70%" /></th>
            ))}
          </tr>
        </thead>
        <tbody>
          <SkeletonTableRows rows={rows} columns={columns} />
        </tbody>
      </table>
    </div>
  );
}

/**
 * Whole-page placeholder: a heading plus a configurable body. Used where the page previously
 * rendered a bare "Loading…" and therefore had no shape at all.
 */
export function SkeletonPage({ title = true, children, label = 'Loading page…' }) {
  return (
    <SkeletonRegion label={label}>
      {title && <Skeleton width={220} height={20} style={{ marginBottom: 18 }} />}
      {children}
    </SkeletonRegion>
  );
}

/** Field label + input pair, matching `.field`. */
export function SkeletonField({ labelWidth = '30%' }) {
  return (
    <div className="field">
      <Skeleton width={labelWidth} height={10} style={{ marginBottom: 6 }} />
      <Skeleton height={38} />
    </div>
  );
}

export function SkeletonForm({ fields = 4 }) {
  return (
    <>
      {Array.from({ length: fields }).map((_, i) => <SkeletonField key={i} />)}
    </>
  );
}

/** Circular placeholder - used for the avatar block on Profile. */
export function SkeletonAvatar({ size = 56 }) {
  return <Skeleton width={size} height={size} radius="50%" />;
}

/**
 * Page title (+ optional action buttons on the right), matching the `h3 { … }` heading and
 * `.btn-row` pattern every list page opens with.
 */
export function SkeletonPageHeader({ titleWidth = 220, actions = 0 }) {
  return (
    <div className="skeleton-page-header">
      <Skeleton width={titleWidth} height={20} />
      {actions > 0 && (
        <div className="btn-row" style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          {Array.from({ length: actions }).map((_, i) => (
            <Skeleton key={i} width={i === 0 ? 180 : 150} height={38} radius={999} />
          ))}
        </div>
      )}
    </div>
  );
}

/** Search input + filter control row, as the list pages render above their tables. */
export function SkeletonFilters({ filters = 2 }) {
  return (
    <div className="skeleton-filters">
      <Skeleton height={38} radius={8} />
      {Array.from({ length: filters }).map((_, i) => (
        <Skeleton key={i} width={120} height={34} radius={999} />
      ))}
    </div>
  );
}

/**
 * The standard composition for a list page: header, filter row, then a table. Kept here rather
 * than repeated on each page so all four list screens load identically.
 */
export function ListPageSkeleton({
  titleWidth = 220, actions = 1, filters = 2, rows = 6, columns = 6, label = 'Loading page…',
}) {
  return (
    <SkeletonRegion label={label}>
      <SkeletonPageHeader titleWidth={titleWidth} actions={actions} />
      <SkeletonFilters filters={filters} />
      <SkeletonTableShell rows={rows} columns={columns} />
    </SkeletonRegion>
  );
}

/**
 * Table markup without its own role="status" - for use INSIDE an existing SkeletonRegion, so the
 * page announces "loading" once rather than once per region.
 */
export function SkeletonTableShell({ rows = 5, columns = 6 }) {
  return (
    <div className="table-scroll">
      <table className="data-table">
        <thead>
          <tr>
            {Array.from({ length: columns }).map((_, c) => (
              <th key={c}><Skeleton height={10} width="70%" /></th>
            ))}
          </tr>
        </thead>
        <tbody>
          <SkeletonTableRows rows={rows} columns={columns} />
        </tbody>
      </table>
    </div>
  );
}
