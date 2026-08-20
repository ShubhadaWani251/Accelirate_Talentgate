import { Navigate, useLocation } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { selectAuthStatus, selectRoleCode } from '../../features/auth/authSlice';
import { FullPageSpinner } from '../loading/Spinner';

export default function ProtectedRoute({ children, allowedRoles }) {
  const status = useSelector(selectAuthStatus);
  const roleCode = useSelector(selectRoleCode);
  const location = useLocation();

  // A brief auth check, not content loading - a spinner is the right signal here, and a page
  // skeleton would be wrong because we don't yet know which page (or role) is coming.
  if (status === 'loading' || status === 'idle') {
    return <FullPageSpinner label="Checking your session" />;
  }

  if (status !== 'authenticated') {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  if (allowedRoles && !allowedRoles.includes(roleCode)) {
    return <Navigate to="/" replace />;
  }

  return children;
}
