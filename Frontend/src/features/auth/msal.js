import { PublicClientApplication } from '@azure/msal-browser';

// Microsoft work-account sign-in, as far as the BROWSER is concerned: get an ID token from
// Entra and hand it to our own backend, which does the actual verification (see
// Backend/api/services/sso.py). Nothing here is a security boundary - a token this file
// obtains is worth exactly what the server's signature, audience and tenant checks say it is.
//
// Configured per environment through Vite env vars rather than fetched from the API, because
// MSAL needs the client id before any request is made. Both unset is the normal state for a
// deployment that has not been given a registration: isSsoConfigured() returns false, Login
// hides the button, and the password form carries on as the only way in.
const clientId = import.meta.env.VITE_SSO_CLIENT_ID || '';
const tenantId = import.meta.env.VITE_SSO_TENANT_ID || '';

// openid/profile/email only. This app asks Entra who someone is and nothing else - it holds
// no delegated Graph permission and reads nothing from the directory, so a wider scope would
// be asking people to consent to access that is never used.
const SCOPES = ['openid', 'profile', 'email'];

export function isSsoConfigured() {
  return Boolean(clientId && tenantId);
}

let instance = null;
let initializing = null;

// MSAL v4 requires an explicit initialize() before any other call, and doing it lazily keeps
// the whole library off the path of a password login, which is the fallback that has to keep
// working when SSO is the thing that is broken.
async function getInstance() {
  if (!isSsoConfigured()) throw new Error('SSO is not configured.');
  if (instance) return instance;
  if (!initializing) {
    const app = new PublicClientApplication({
      auth: {
        clientId,
        // The single-tenant authority. Entra refuses a token request for any other directory
        // at source, so a personal Microsoft account cannot even reach our backend's checks.
        authority: `https://login.microsoftonline.com/${tenantId}`,
        redirectUri: window.location.origin,
      },
      cache: {
        // Session, not local: the ID token is spent the moment it is exchanged for our own
        // session, so there is nothing worth keeping once the tab closes.
        cacheLocation: 'sessionStorage',
      },
    });
    initializing = app.initialize().then(() => {
      instance = app;
      return app;
    }).catch((err) => {
      // Let the next attempt rebuild it rather than caching a dead instance forever.
      initializing = null;
      throw err;
    });
  }
  return initializing;
}

/**
 * Opens the Microsoft sign-in popup and resolves to a raw ID token.
 *
 * A popup rather than a full-page redirect: redirect would mean handling the return leg on
 * every app boot, for a button that only exists on one screen. Browsers allow a popup opened
 * directly from a click, which this always is.
 *
 * Throws with `cancelled: true` when the person simply closed the window, so the caller can
 * stay quiet instead of showing them an error for changing their mind.
 */
export async function signInWithMicrosoft() {
  const app = await getInstance();
  let result;
  try {
    result = await app.loginPopup({ scopes: SCOPES, prompt: 'select_account' });
  } catch (err) {
    const code = err?.errorCode || '';
    if (code === 'user_cancelled' || code === 'popup_window_error' || code.includes('cancel')) {
      const cancelled = new Error('Sign-in was cancelled.');
      cancelled.cancelled = code === 'user_cancelled' || code.includes('cancel');
      cancelled.popupBlocked = code === 'popup_window_error';
      throw cancelled;
    }
    throw err;
  }
  if (!result?.idToken) throw new Error('Microsoft did not return a usable sign-in token.');
  return result.idToken;
}

/**
 * Clears MSAL's own cached account.
 *
 * Deliberately local-only - it does NOT sign the person out of Microsoft. Ending an
 * organisation-wide Microsoft session because somebody left one application would be well
 * beyond what Log Out means here, and would take their mail and Teams with it.
 */
export async function forgetMicrosoftAccount() {
  if (!isSsoConfigured() || !instance) return;
  try {
    const accounts = instance.getAllAccounts();
    accounts.forEach((account) => instance.clearCache({ account }));
  } catch {
    // Best effort. A stale MSAL cache entry costs an extra account picker, nothing more.
  }
}
