import { Link, useSearchParams } from 'react-router-dom';
import BrandHeader from '../../components/layout/BrandHeader';
import BrandFooter from '../../components/layout/BrandFooter';

const CONSOLE_LABELS = { admin: 'Administrator', ta: 'Staffing User' };

// The wireframe's "Signed Out" screen. Reached from a deliberate Logout, or from the idle-timeout
// auto-logout (useIdleLogout.js) - both are the app's own decision to end the session, unlike an
// expired/rejected session, which still bounces to /login since the user hasn't chosen to leave
// and "you have been logged out" would be misleading there.
//
// Role/reason arrive as query params, not router navigation state - useLogout.js reaches this
// screen via a real browser navigation (window.location.assign), not React Router's navigate(),
// so there is no SPA-level location.state to read here.
export default function LoggedOut() {
  const [searchParams] = useSearchParams();
  const roleCode = searchParams.get('role');
  const consoleName = CONSOLE_LABELS[roleCode];
  const isIdle = searchParams.get('reason') === 'idle';

  return (
    <>
      <BrandHeader roleCode={roleCode} />
      <div className="auth-shell">
        <div className="auth-card" style={{ textAlign: 'center' }}>
          <h3>Signed Out</h3>
          <div className="auth-sub">
            {isIdle
              ? `You were logged out of the ${consoleName ? `${consoleName} ` : ''}console after 1 hour of inactivity.`
              : `You have been logged out of the ${consoleName ? `${consoleName} ` : ''}console.`}
          </div>
          <Link to="/login" className="btn primary block" style={{ textDecoration: 'none' }}>
            Log In Again
          </Link>
        </div>
      </div>
      <BrandFooter roleCode={roleCode} />
    </>
  );
}
