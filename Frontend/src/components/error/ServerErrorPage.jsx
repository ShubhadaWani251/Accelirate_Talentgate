import { useState } from 'react';
import ErrorPage from './ErrorPage';
import { ServerErrorIllustration } from './ErrorIllustration';

/**
 * 500 / unexpected-error page.
 *
 * Deliberately shows NO technical detail - no status text, no response body, no stack. Callers
 * pass an `onRetry` that re-runs the failed operation (a page's own loader) or, absent that, this
 * falls back to reloading the current route.
 *
 * Retry semantics: one attempt per click, attempts are counted, and if it fails again the user
 * stays on this error state rather than being bounced anywhere. Nothing retries automatically.
 */
export default function ServerErrorPage({ onRetry, standalone = false }) {
  const [attempts, setAttempts] = useState(0);

  async function handleRetry() {
    setAttempts((n) => n + 1);
    if (onRetry) {
      await onRetry();
      return;
    }
    // No specific operation to re-run - reload the current route as a last resort.
    window.location.reload();
  }

  return (
    <ErrorPage
      standalone={standalone}
      variant="server"
      illustration={<ServerErrorIllustration />}
      code="500"
      title="Something Went Wrong"
      message="Something went wrong while processing your request. Please try again."
      onRetry={handleRetry}
      retryFailed={attempts > 0}
      retryFailedMessage={
        'That didn’t work. Please wait a moment and try once more - if it keeps happening, '
        + 'contact the Staffing team so they can look into it.'
      }
    />
  );
}
