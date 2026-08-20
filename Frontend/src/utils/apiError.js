/**
 * Classifies an axios error so a page can react to WHAT went wrong instead of treating every
 * failure as a server fault.
 *
 * The point of this file is the negative case: a 403 or a 404 must NOT render the 500 page. Only
 * a genuine server fault (5xx) or a request that never reached the server (network/timeout) does.
 *
 *   400 / 422 -> 'validation'  handled inline by the form that submitted it (toast today)
 *   401       -> 'auth'        axiosClient's interceptor already refreshes/redirects
 *   403       -> 'forbidden'   the user is known but not allowed
 *   404       -> 'notfound'    the RESOURCE is missing (distinct from an unknown route)
 *   5xx       -> 'server'      -> ServerErrorPage
 *   no status -> 'network'     -> ServerErrorPage (nothing came back at all)
 */
export const ErrorKind = {
  VALIDATION: 'validation',
  AUTH: 'auth',
  FORBIDDEN: 'forbidden',
  NOT_FOUND: 'notfound',
  SERVER: 'server',
  NETWORK: 'network',
  UNKNOWN: 'unknown',
};

export function classifyApiError(err) {
  const status = err?.response?.status;

  // No response at all - request never completed (offline, DNS, timeout, CORS failure).
  if (!status) return ErrorKind.NETWORK;

  if (status >= 500) return ErrorKind.SERVER;
  if (status === 404) return ErrorKind.NOT_FOUND;
  if (status === 403) return ErrorKind.FORBIDDEN;
  if (status === 401) return ErrorKind.AUTH;
  if (status === 400 || status === 422) return ErrorKind.VALIDATION;
  return ErrorKind.UNKNOWN;
}

/**
 * True only for failures that justify replacing the page with the 500 error page. Everything else
 * keeps its existing, more specific handling.
 */
export function isServerFault(err) {
  const kind = classifyApiError(err);
  return kind === ErrorKind.SERVER || kind === ErrorKind.NETWORK;
}

/** True when the requested resource itself doesn't exist, so the page can show a 404 instead. */
export function isResourceMissing(err) {
  return classifyApiError(err) === ErrorKind.NOT_FOUND;
}
