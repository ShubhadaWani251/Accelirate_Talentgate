// Display helpers for the 24-hour Draft batch lifetime.
//
// The backend is the authority on all of this (Backend/api/services/draft_expiry.py owns the
// rule, the scheduled cleanup and the API refusals). Everything here is presentation: it
// formats the `draft_expires_at` timestamp the API sends so a TA can see how long a draft has
// left before it is deleted. Nothing in the UI causes, delays or prevents that deletion, and a
// countdown that reaches zero on screen means "the server will remove this", not "removed".

// Parses the ISO string the API sends for a draft (null for every other status).
export function parseExpiry(batch) {
  if (!batch?.draft_expires_at) return null;
  const at = new Date(batch.draft_expires_at);
  return Number.isNaN(at.getTime()) ? null : at;
}

// "Expires in 8h 32m" / "Expires in 14m" / "Expiring now".
//
// Rounds down, so a draft that reads "1h left" really does have at least an hour - overstating
// the time remaining is the one error worth avoiding here.
export function formatTimeLeft(expiresAt, now = Date.now()) {
  if (!expiresAt) return null;
  const msLeft = expiresAt.getTime() - now;
  if (msLeft <= 0) return 'Expiring now';

  const totalMinutes = Math.floor(msLeft / 60000);
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (hours > 0) return `Expires in ${hours}h ${minutes}m`;
  if (minutes > 0) return `Expires in ${minutes}m`;
  return 'Expires in under a minute';
}

// The absolute deadline, in the viewer's own timezone - the server sends a UTC instant and the
// browser renders it locally, so there's no manual offset arithmetic anywhere.
export function formatExpiryDate(expiresAt) {
  if (!expiresAt) return null;
  return expiresAt.toLocaleString(undefined, {
    day: 'numeric', month: 'short', year: 'numeric', hour: 'numeric', minute: '2-digit',
  });
}

// Under three hours left is worth colouring; anything more is just information.
export function isExpiringSoon(expiresAt, now = Date.now()) {
  if (!expiresAt) return false;
  return expiresAt.getTime() - now <= 3 * 60 * 60 * 1000;
}
