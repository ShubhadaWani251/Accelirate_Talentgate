import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import ErrorPage from './ErrorPage';
import { NotFoundIllustration } from './ErrorIllustration';

/**
 * 404, rendered by the router's catch-all route.
 *
 * Retry semantics: re-navigate to the same path once. If the route genuinely doesn't exist this
 * lands back here - which is why the attempt is COUNTED and, from the second attempt on, the page
 * says so plainly instead of silently doing nothing. It never auto-retries and never redirects
 * elsewhere, so there is no redirect loop.
 */
export default function NotFoundPage({ standalone = true }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [attempted, setAttempted] = useState(false);

  function handleRetry() {
    setAttempted(true);
    // `replace` keeps the history stack from filling up with identical dead entries as the
    // candidate retries, so the browser Back button still works normally afterwards.
    navigate(location.pathname + location.search, { replace: true });
  }

  return (
    <ErrorPage
      standalone={standalone}
      illustration={<NotFoundIllustration />}
      code="404"
      title="Page Not Found"
      message="The page you're looking for doesn't exist or may have been moved."
      onRetry={handleRetry}
      retryFailed={attempted}
      retryFailedMessage={
        'This page still isn’t available. The address may be mistyped or the page may have '
        + 'been removed - try navigating from the menu instead.'
      }
      secondaryAction={
        // Navigation back into the app, deliberately a link rather than a second button so it
        // doesn't compete with the single primary Retry action.
        <Link to="/" className="link-text">Go to Home</Link>
      }
    />
  );
}
