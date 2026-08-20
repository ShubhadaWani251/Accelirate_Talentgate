import BrandHeader from '../layout/BrandHeader';
import BrandFooter from '../layout/BrandFooter';
import RetryButton from './RetryButton';

/**
 * Shared shell for the 404 and 500 pages - only the status code, wording and accent colour
 * differ, so the layout, retry affordance and "retry didn't help" feedback live here once.
 *
 * `standalone` renders the brand header/footer too, for when this is the whole page (an
 * unauthenticated 404, or an error boundary that has replaced the entire app shell). Inside the
 * authenticated layout the header/nav/footer are already on screen, so it renders bare and the
 * app's existing navigation stays available.
 */
export default function ErrorPage({
  code,
  title,
  message,
  onRetry,
  retryLabel = 'Retry',
  retryFailed = false,
  retryFailedMessage,
  variant = 'default',   // 'default' | 'server'
  standalone = false,
  secondaryAction = null,
  illustration = null,
}) {
  const body = (
    <div className="error-page">
      <div className={`error-card${variant === 'server' ? ' is-server' : ''}`}>
        {illustration}
        {/* The code is decorative duplication of the title text for sighted users; the heading
            below carries the meaning, so it isn't announced twice. */}
        <div className="error-code" aria-hidden="true">{code}</div>
        <h1 className="error-title">{title}</h1>
        <p className="error-message">{message}</p>

        {retryFailed && (
          <div className="error-note" role="alert">
            {retryFailedMessage}
          </div>
        )}

        <div className="error-actions">
          {onRetry && <RetryButton onRetry={onRetry} label={retryLabel} />}
          {secondaryAction}
        </div>
      </div>
    </div>
  );

  if (!standalone) return body;

  return (
    <div className="app-shell">
      <BrandHeader />
      {body}
      <BrandFooter />
    </div>
  );
}
