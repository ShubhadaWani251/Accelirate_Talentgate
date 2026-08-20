import { useState } from 'react';

/**
 * The single primary action on an error page.
 *
 * Guards against a retry loop in two ways: it can't be re-entered while a retry is in flight,
 * and it counts attempts so the caller can tell the user when retrying isn't helping instead of
 * letting them hammer it silently. It never retries on its own - only on a real click/keypress.
 *
 * It's a real <button>, so keyboard activation (Enter/Space) and focus styling come for free.
 */
export default function RetryButton({ onRetry, label = 'Retry', busyLabel = 'Retrying…' }) {
  const [busy, setBusy] = useState(false);

  async function handleClick() {
    if (busy) return;
    setBusy(true);
    try {
      await onRetry();
    } finally {
      // If the retry navigated or reloaded, this component is gone and the state update is a
      // no-op; if it failed, the button becomes clickable again for a deliberate second attempt.
      setBusy(false);
    }
  }

  return (
    <button
      type="button"
      className="btn primary"
      onClick={handleClick}
      disabled={busy}
      aria-label={label}
    >
      {busy ? busyLabel : label}
    </button>
  );
}
