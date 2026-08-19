// requestFullscreen() does not reliably settle. Depending on browser and context it can resolve,
// reject, or simply hang forever with no rejection (observed first-hand in an embedded browser:
// a real click produced a promise that never settled). Anything that `await`s it directly can
// therefore strand the candidate on a screen that never advances - which is why every caller goes
// through this helper instead.
//
// Never rejects, and always settles within TIMEOUT_MS. Resolves to whether full-screen actually
// ended up active, so callers can decide what to do without ever being blocked.
const TIMEOUT_MS = 1200;

export const FULLSCREEN_SUPPORTED = typeof document !== 'undefined' &&
  typeof document.documentElement.requestFullscreen === 'function';

export function isFullscreen() {
  return Boolean(document.fullscreenElement);
}

export function enterFullscreen() {
  if (!FULLSCREEN_SUPPORTED) return Promise.resolve(false);
  if (isFullscreen()) return Promise.resolve(true);

  let settle;
  const settled = new Promise((resolve) => { settle = resolve; });

  // Bounded: a hung promise can never hold the candidate up longer than this.
  const timer = setTimeout(() => settle(isFullscreen()), TIMEOUT_MS);
  const finish = () => {
    clearTimeout(timer);
    settle(isFullscreen());
  };

  try {
    const result = document.documentElement.requestFullscreen();
    // Older APIs return undefined rather than a promise.
    if (result && typeof result.then === 'function') {
      result.then(finish, finish);
    } else {
      finish();
    }
  } catch {
    finish();
  }

  return settled;
}

export function exitFullscreen() {
  if (!isFullscreen() || !document.exitFullscreen) return Promise.resolve();
  try {
    const result = document.exitFullscreen();
    return result && typeof result.catch === 'function' ? result.catch(() => {}) : Promise.resolve();
  } catch {
    return Promise.resolve();
  }
}
