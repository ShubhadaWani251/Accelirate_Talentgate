import { Navigate, useLocation } from 'react-router-dom';
import { useSelector } from 'react-redux';
import {
  selectAuthStatus, selectMustChangePassword, selectRoleCode,
} from '../../features/auth/authSlice';
import { FullPageSpinner } from '../loading/Spinner';

// Where someone on a handover password is sent, and the one protected route they may reach
// while they are on one - it is where the change-password form lives.
const CHANGE_PASSWORD_PATH = '/profile';

export default function ProtectedRoute({ children, allowedRoles }) {
  const status = useSelector(selectAuthStatus);
  const roleCode = useSelector(selectRoleCode);
  const mustChangePassword = useSelector(selectMustChangePassword);
  const location = useLocation();

  // A brief auth check, not content loading - a spinner is the right signal here, and a page
  // skeleton would be wrong because we don't yet know which page (or role) is coming.
  if (status === 'loading' || status === 'idle') {
    return <FullPageSpinner label="Checking your session" />;
  }

  if (status !== 'authenticated') {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  // Checked before the role gate: an account still on a password somebody else chose has to
  // replace it before doing anything, whatever its role. This is a redirect, not the control -
  // the server independently refuses every staff endpoint for such an account (see
  // api/permissions.py), so a stale build or a hand-typed URL gains nothing.
  if (mustChangePassword && location.pathname !== CHANGE_PASSWORD_PATH) {
    return <Navigate to={CHANGE_PASSWORD_PATH} replace />;
  }

  if (allowedRoles && !allowedRoles.includes(roleCode)) {
    return <Navigate to="/" replace />;
  }

  return children;
}
