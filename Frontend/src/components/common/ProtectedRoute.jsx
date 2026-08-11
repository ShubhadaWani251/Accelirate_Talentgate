import { Navigate, useLocation } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { selectAuthStatus, selectRoleCode } from '../../features/auth/authSlice';

export default function ProtectedRoute({ children, allowedRoles }) {
  const status = useSelector(selectAuthStatus);
  const roleCode = useSelector(selectRoleCode);
  const location = useLocation();

  if (status === 'loading' || status === 'idle') {
    return <div className="loading-splash">Loading...</div>;
  }

  if (status !== 'authenticated') {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  if (allowedRoles && !allowedRoles.includes(roleCode)) {
    return <Navigate to="/" replace />;
  }

  return children;
}
