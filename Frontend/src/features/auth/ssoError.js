// A failed Microsoft sign-in has to say so on the login screen, but the two are separated by a
// full page load: the failure is discovered during app boot at the redirect URI ("/"), and the
// login screen is a fresh render after that boot sends the person back to /login. Redux state
// does not survive the navigation that caused it, so the message travels through sessionStorage
// instead - the same tab, cleared the moment it is read, and gone when the tab closes.
//
// sessionStorage rather than localStorage: a stale error message surfacing in a different tab,
// or tomorrow, would be worse than no message at all.
const KEY = 'accelieval_sso_error';

export function stashSsoError(message) {
  try {
    sessionStorage.setItem(KEY, message);
  } catch { /* private browsing or storage blocked - the message is the thing lost, not the app */ }
}

/** Returns the stashed message and removes it, so a reload doesn't show it a second time. */
export function takeSsoError() {
  try {
    const message = sessionStorage.getItem(KEY);
    if (message) sessionStorage.removeItem(KEY);
    return message || '';
  } catch {
    return '';
  }
}

/**
 * Turns whatever a failed sign-in threw into one sentence a person can act on.
 *
 * The error CODE is kept rather than swallowed. A generic "could not be completed" turns every
 * distinct failure - a registration missing this origin, a declined consent, an expired
 * request, a directory that refuses the account - into the same dead end, and the code is the
 * only part of it that someone can act on or quote to whoever administers the directory.
 */
export function describeSsoError(err) {
  // A server rejection (unknown address, deactivated account, wrong directory) already carries
  // a message written for the person reading it.
  const serverDetail = err?.response?.data?.detail;
  if (serverDetail) return serverDetail;

  const code = err?.errorCode || err?.name || '';
  const detail = err?.errorMessage || err?.message || '';
  return `Microsoft sign-in could not be completed${code ? ` (${code})` : ''}. `
    + 'Try again, or sign in with your password below.'
    + (detail ? ` Details: ${detail}` : '');
}
