/**
 * Reusable spinner for SHORT, action-scoped waits - button submits, quick API calls, and
 * full-page blocking operations. Page/content loading uses a skeleton instead (see Skeleton.jsx);
 * the two are deliberately not interchangeable.
 *
 * Pure CSS (one rotate keyframe on a bordered circle) - no icon library, no SVG payload.
 * Accessibility: the element carries role="status" + an aria-label, so assistive tech announces
 * "Loading" without any visible "Loading…" text needing to exist.
 */

const SIZES = { sm: 14, md: 18, lg: 28, xl: 40 };

export default function Spinner({ size = 'md', label = 'Loading', inline = false, className = '' }) {
  const px = SIZES[size] || SIZES.md;
  return (
    <span
      className={`spinner${inline ? ' spinner-inline' : ''} ${className}`}
      style={{ width: px, height: px, borderWidth: Math.max(2, Math.round(px / 8)) }}
      role="status"
      aria-label={label}
    />
  );
}

/**
 * Centred spinner for a whole region/page that must block until an action finishes. Used for
 * short blocking operations only - anything that is really "content still loading" should render
 * a skeleton so the layout doesn't jump when data arrives.
 */
export function FullPageSpinner({ label = 'Loading' }) {
  return (
    <div className="spinner-page" role="status" aria-label={label}>
      <Spinner size="xl" label={label} />
    </div>
  );
}

/**
 * Button content: shows a spinner before the label while `loading`, and just the label otherwise.
 *
 * Deliberately keeps the SAME label text in both states so the button doesn't change width
 * mid-action (the old pattern swapped "Save" for "Saving…", which resized the button and moved
 * everything next to it). Pair with `disabled={loading}` on the button to stop double submits.
 */
export function ButtonSpinner({ loading = false, children, size = 'sm' }) {
  return (
    <>
      {loading && <Spinner size={size} inline />}
      {children}
    </>
  );
}
