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

// Imported dynamically, and initialised lazily, so that neither the download nor the setup of
// a sizeable library sits on the path of a password login - the fallback that has to keep
// working when SSO is the thing that is broken. Everything a normal page load needs from this
// module (isSsoConfigured, hasMicrosoftRedirectResponse) is a synchronous look at a constant or
// at the URL, so nothing here is fetched until somebody actually signs in with Microsoft.
//
// MSAL v4 additionally requires an explicit initialize() before any other call.
async function getInstance() {
  if (!isSsoConfigured()) throw new Error('SSO is not configured.');
  if (instance) return instance;
  // `initializing` is assigned synchronously, before the first await below is ever reached, so
  // two concurrent callers share one instance. Building a second PublicClientApplication over
  // the same sessionStorage would be a real hazard rather than mere waste, and concurrent
  // callers are the normal case here, not an exotic one: StrictMode invokes the boot effect
  // twice.
  if (!initializing) {
    initializing = buildInstance().catch((err) => {
      // Let the next attempt rebuild it rather than caching a dead instance forever.
      initializing = null;
      throw err;
    });
  }
  return initializing;
}

async function buildInstance() {
  const { PublicClientApplication } = await import('@azure/msal-browser');
  const app = new PublicClientApplication({
    auth: {
      clientId,
      // The single-tenant authority. Entra refuses a token request for any other directory
      // at source, so a personal Microsoft account cannot even reach our backend's checks.
      authority: `https://login.microsoftonline.com/${tenantId}`,
      // Must match a redirect URI registered under the app registration's SINGLE-PAGE
      // APPLICATION platform (not Web, not Mobile): the token exchange is a cross-origin
      // fetch from this browser, and Entra only allows that for the SPA platform. Registered
      // without a trailing slash, which is what window.location.origin produces.
      redirectUri: window.location.origin,
      // Land on the redirect URI and stay there rather than having MSAL bounce the browser
      // back to whichever page started the sign-in. "/" is RoleHome, which sends the person
      // to their own dashboard once the session exists - the destination either way, reached
      // without the extra hop.
      navigateToLoginRequestUrl: false,
    },
    cache: {
      // Session, not local: the ID token is spent the moment it is exchanged for our own
      // session, so there is nothing worth keeping once the tab closes. The in-flight
      // request state also lives here, which survives the redirect because it is the same
      // tab throughout - the reason this flow needs no cross-window anything.
      cacheLocation: 'sessionStorage',
    },
  });
  await app.initialize();
  instance = app;
  return app;
}

/**
 * Whether this page load is Entra returning from a sign-in.
 *
 * Deliberately a cheap synchronous look at the URL, so app boot can skip loading and
 * initialising MSAL entirely on the overwhelming majority of loads that are not a sign-in
 * return - including every password login, which must keep working when SSO does not.
 *
 * Checks for a state parameter AND an outcome: a normally-opened page never carries both.
 */
export function hasMicrosoftRedirectResponse() {
  const hash = window.location.hash;
  return hash.includes('state=') && (hash.includes('code=') || hash.includes('error='));
}

/**
 * Sends the browser to Microsoft to sign in. Does not resolve - the page is navigated away.
 *
 * A full-page redirect rather than a popup, which is what this used to be. The popup flow
 * depends on the opened window and the window that opened it being able to talk to each other
 * across a cross-origin round trip, and that link is governed by Cross-Origin-Opener-Policy,
 * browser popup blocking, and a browsing-context-group switch on the return leg that no header
 * on our side reliably prevents. All of it sat between a person clicking the button and
 * getting in, and none of it was load-bearing: a redirect needs no second window, so none of
 * those failure modes exist. It is also what was asked for - sign-in happening in the tab the
 * person is already looking at.
 */
export async function startMicrosoftSignIn() {
  const app = await getInstance();
  // select_account rather than silent: this is an explicit "sign in" click, and on a shared
  // or multi-account machine picking up whichever account Microsoft last used would sign
  // somebody into the wrong console.
  await app.loginRedirect({ scopes: SCOPES, prompt: 'select_account' });
}

/**
 * Completes a sign-in that Entra has just redirected back from, and resolves to a raw ID token.
 *
 * Resolves to null when this load is not a sign-in return, so app boot can call it
 * unconditionally. Rejects with MSAL's own error (errorCode/errorMessage intact) when Entra
 * refused - the caller shows the code, because it is the only thing that distinguishes a
 * misconfigured registration from a declined consent from an expired request.
 */
export async function completeMicrosoftSignIn() {
  if (!isSsoConfigured() || !hasMicrosoftRedirectResponse()) return null;
  const app = await getInstance();
  // Reads the response out of the URL, finishes the PKCE exchange, and clears the fragment.
  // Returns null if the hash turns out not to be one of ours after all.
  const result = await app.handleRedirectPromise();
  return result?.idToken || null;
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
    await Promise.all(accounts.map((account) => instance.clearCache({ account })));
  } catch {
    // Best effort. A stale MSAL cache entry costs an extra account picker, nothing more.
  }
}
