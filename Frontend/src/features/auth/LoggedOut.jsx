import { Link, useLocation } from 'react-router-dom';
import BrandHeader from '../../components/layout/BrandHeader';
import BrandFooter from '../../components/layout/BrandFooter';

const CONSOLE_LABELS = { admin: 'Administrator', ta: 'Staffing User' };

// The wireframe's "Signed Out" screen. Reached only from a deliberate Logout - an expired or
// rejected session still bounces to /login, since in that case the user hasn't chosen to leave
// and telling them "you have been logged out" would be misleading.
export default function LoggedOut() {
  const { state } = useLocation();
  // Role is captured before the session is cleared and handed over in navigation state; it's
  // gone from the store by the time this renders, so fall back to unqualified wording.
  const consoleName = CONSOLE_LABELS[state?.roleCode];

  return (
    <>
      <BrandHeader roleCode={state?.roleCode} />
      <div className="auth-shell">
        <div className="auth-card" style={{ textAlign: 'center' }}>
          <h3>Signed Out</h3>
          <div className="auth-sub">
            You have been logged out of the {consoleName ? `${consoleName} ` : ''}console.
          </div>
          <Link to="/login" className="btn primary block" style={{ textDecoration: 'none' }}>
            Log In Again
          </Link>
        </div>
      </div>
      <BrandFooter roleCode={state?.roleCode} />
    </>
  );
}
