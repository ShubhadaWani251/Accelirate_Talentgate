// A drawing of the FRONT of an Aadhaar card, marking the two things identity verification
// actually reads: the number and the date of birth.
//
// Candidates were photographing the back, or a corner, or the card at an angle that cut the
// number off, and only discovered the problem after the capture came back unreadable. Showing
// the shape beforehand is cheaper than a retake, and the same drawing goes into the invitation
// email (email_templates.AADHAAR_LAYOUT_BLOCK) so the two never say different things.
//
// Every field is a placeholder. This is a layout, deliberately not a specimen of anybody's
// identity document - there is no real name, number, date or photograph in it.
//
// Inline SVG rather than an image file: it stays sharp at any size, needs no asset pipeline,
// and takes its colours from the theme so it works in both light and dark.
export default function AadhaarLayoutDiagram({ width = 320 }) {
  const NEEDED = 'var(--brand-red, #c62828)';
  const LINE = 'var(--line-soft, #d6dae0)';
  const INK = 'var(--muted, #6b7280)';

  return (
    <svg
      viewBox="0 0 320 200"
      width={width}
      style={{ maxWidth: '100%', height: 'auto', display: 'block' }}
      role="img"
      aria-label={
        'Diagram of the front of an Aadhaar card. The date of birth sits in the middle of the '
        + 'card and the 12-digit number runs along the bottom. Both must be readable in your '
        + 'photo.'
      }
    >
      <rect x="1" y="1" width="318" height="198" rx="10"
            fill="var(--surface, #ffffff)" stroke={LINE} strokeWidth="1.5" />

      {/* The tricolour band across the top, the thing that makes it recognisable at a glance. */}
      <rect x="1" y="1" width="318" height="7" rx="3" fill="#ff9933" />
      <rect x="1" y="8" width="318" height="7" fill="#138808" />
      <text x="160" y="32" textAnchor="middle" fontSize="11" fill={INK}>Government of India</text>

      {/* Photo, left - where a candidate's own photo sits. */}
      <rect x="18" y="46" width="66" height="80" rx="4" fill="none" stroke={LINE} strokeWidth="1.5" />
      <circle cx="51" cy="70" r="12" fill="none" stroke={LINE} strokeWidth="1.5" />
      <path d="M32 106 a19 19 0 0 1 38 0" fill="none" stroke={LINE} strokeWidth="1.5" />
      {/* Inside the frame, not under it - a caption sitting below the box reads as a label for
          whatever comes next rather than for the box itself. */}
      <text x="51" y="120" textAnchor="middle" fontSize="8.5" fill={INK}>photo</text>

      {/* Name / parent - present on the card, not read by verification, so drawn plainly. */}
      <text x="98" y="58" fontSize="10" fill={INK}>Your Name</text>
      <text x="98" y="74" fontSize="9" fill={INK}>Father / Mother : …</text>

      {/* DOB - one of the two fields that must be readable. */}
      <text x="98" y="94" fontSize="10.5" fill={NEEDED} fontWeight="600">
        DOB : DD/MM/YYYY
      </text>
      <text x="98" y="110" fontSize="9" fill={INK}>Male / Female</text>

      {/* QR, right. Decorative here - a few squares read as a QR without pretending to be one. */}
      <rect x="246" y="60" width="56" height="56" rx="3" fill="none" stroke={LINE} strokeWidth="1.5" />
      {/* A fixed pattern rather than a checkerboard or anything random: dense enough to read as
          a QR at a glance, and stable so the drawing looks the same every render. */}
      {[
        [1, 1, 0, 1], [1, 0, 1, 0], [0, 1, 1, 1], [1, 1, 0, 1],
      ].map((row, r) => row.map((on, c) => (on ? (
        <rect key={`${r}-${c}`} x={252 + c * 12} y={66 + r * 12} width="8" height="8"
              rx="1" fill={LINE} />
      ) : null)))}

      {/* The 12-digit number - the other field that must be readable. First eight may be
          masked, which is why they are drawn as X. */}
      <text x="160" y="160" textAnchor="middle" fontSize="16" letterSpacing="2.5"
            fill={NEEDED} fontWeight="700" fontFamily="Consolas, Menlo, monospace">
        XXXX XXXX 1234
      </text>

      <text x="160" y="182" textAnchor="middle" fontSize="8.5" fill={NEEDED}>
        both red lines must be readable in your photo
      </text>
    </svg>
  );
}
