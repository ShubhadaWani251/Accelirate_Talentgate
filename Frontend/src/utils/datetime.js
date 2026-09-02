// <input type="datetime-local"> works in the browser's local timezone and wants/returns
// "YYYY-MM-DDTHH:mm" with no offset - these convert to/from a real ISO/UTC string.
export function toDatetimeLocalValue(isoString) {
  if (!isoString) return '';
  const d = new Date(isoString);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function fromDatetimeLocalValue(localValue) {
  if (!localValue) return null;
  return new Date(localValue).toISOString();
}

export function formatDateTime(isoString) {
  if (!isoString) return '—';
  return new Date(isoString).toLocaleString(undefined, {
    day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

// Date-only fields (Date of Birth) - always DD/MM/YYYY, the one format used everywhere it's
// typed too (the upload template, every edit form), regardless of the viewer's own locale.
// isoDate is a plain 'YYYY-MM-DD' (DRF's default DateField wire format, no time component) -
// parsed with a fixed UTC time rather than `new Date(isoDate)` alone, which some browsers
// interpret as local midnight and others as UTC midnight, silently shifting the displayed day
// by one for viewers behind UTC.
export function formatDateDMY(isoDate) {
  if (!isoDate) return '—';
  const d = new Date(`${isoDate}T00:00:00Z`);
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(d.getUTCDate())}/${pad(d.getUTCMonth() + 1)}/${d.getUTCFullYear()}`;
}

// 'YYYY-MM-DD' (the API's wire format) -> 'DD/MM/YYYY', for PREFILLING an editable Date of
// Birth text field. Distinct from formatDateDMY, which returns '—' for a blank value - fine
// for read-only display, wrong here since an em-dash left sitting in an editable box isn't a
// value the candidate ever had, it's just noise the reviewer would have to delete first.
export function isoToDMY(isoDate) {
  if (!isoDate) return '';
  const [y, m, d] = isoDate.split('-');
  return `${d}/${m}/${y}`;
}
