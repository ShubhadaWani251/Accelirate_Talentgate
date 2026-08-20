/**
 * Inline SVG illustrations for the error pages - so 404 and 500 are distinguishable at a glance,
 * not just by their number. Inline rather than image files or an icon library: no extra request,
 * no dependency, and they inherit the page's theme colours via currentColor/CSS variables.
 *
 * Decorative only (aria-hidden) - the heading and message carry the meaning.
 */

/** 404: a magnifying glass over an empty page - "we looked, it isn't there". */
export function NotFoundIllustration() {
  return (
    <svg className="error-illustration" viewBox="0 0 120 96" role="presentation" aria-hidden="true">
      {/* page */}
      <rect x="22" y="10" width="58" height="76" rx="6" fill="var(--accent-soft)" stroke="var(--brand-blue)" strokeWidth="2.5" />
      {/* torn/empty content lines */}
      <line x1="34" y1="30" x2="64" y2="30" stroke="var(--brand-blue)" strokeWidth="3" strokeLinecap="round" opacity=".45" />
      <line x1="34" y1="42" x2="56" y2="42" stroke="var(--brand-blue)" strokeWidth="3" strokeLinecap="round" opacity=".3" />
      <line x1="34" y1="54" x2="60" y2="54" stroke="var(--brand-blue)" strokeWidth="3" strokeLinecap="round" opacity=".2" />
      {/* magnifier */}
      <circle cx="79" cy="58" r="19" fill="#fff" stroke="var(--brand-navy)" strokeWidth="3.5" />
      <line x1="92" y1="72" x2="106" y2="86" stroke="var(--brand-navy)" strokeWidth="5" strokeLinecap="round" />
      {/* question mark inside the lens */}
      <text x="79" y="65" textAnchor="middle" fontSize="20" fontWeight="700" fill="var(--brand-navy)">?</text>
    </svg>
  );
}

/** 500: a server/stack with a warning - "our side broke", visually unlike the 404 magnifier. */
export function ServerErrorIllustration() {
  return (
    <svg className="error-illustration" viewBox="0 0 120 96" role="presentation" aria-hidden="true">
      {/* stacked server units */}
      <rect x="18" y="14" width="84" height="22" rx="5" fill="var(--red-bg)" stroke="var(--brand-red-dark)" strokeWidth="2.5" />
      <rect x="18" y="42" width="84" height="22" rx="5" fill="var(--red-bg)" stroke="var(--brand-red-dark)" strokeWidth="2.5" />
      <rect x="18" y="70" width="84" height="18" rx="5" fill="#fff" stroke="var(--brand-red-dark)" strokeWidth="2.5" opacity=".5" />
      {/* status lights */}
      <circle cx="29" cy="25" r="3.5" fill="var(--brand-red-dark)" />
      <circle cx="29" cy="53" r="3.5" fill="var(--brand-red-dark)" opacity=".55" />
      <line x1="40" y1="25" x2="72" y2="25" stroke="var(--brand-red-dark)" strokeWidth="2.5" strokeLinecap="round" opacity=".35" />
      <line x1="40" y1="53" x2="64" y2="53" stroke="var(--brand-red-dark)" strokeWidth="2.5" strokeLinecap="round" opacity=".25" />
      {/* warning badge */}
      <path d="M88 40 L104 68 L72 68 Z" fill="#fff" stroke="var(--brand-red)" strokeWidth="3" strokeLinejoin="round" />
      <line x1="88" y1="50" x2="88" y2="59" stroke="var(--brand-red)" strokeWidth="3" strokeLinecap="round" />
      <circle cx="88" cy="64" r="1.9" fill="var(--brand-red)" />
    </svg>
  );
}
