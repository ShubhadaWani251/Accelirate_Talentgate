import { useCallback } from 'react';
import { Outlet } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { selectRoleCode } from '../../features/auth/authSlice';
import useLogout from '../../features/auth/useLogout';
import useIdleLogout from '../../features/auth/useIdleLogout';
import BrandHeader from './BrandHeader';
import BrandFooter from './BrandFooter';
import AppNav from './AppNav';

export default function ProtectedLayout() {
  const roleCode = useSelector(selectRoleCode);
  const logout = useLogout();
  // Mounted once here, at the root of the whole protected (staff/admin) route tree - see
  // useIdleLogout's own docstring for why this must never wrap the candidate exam portal.
  const onIdle = useCallback(() => { logout('idle'); }, [logout]);
  useIdleLogout(onIdle);

  return (
    <div className="app-shell">
      <BrandHeader roleCode={roleCode} />
      <AppNav />
      <main className="page-body">
        <Outlet />
      </main>
      <BrandFooter roleCode={roleCode} />
    </div>
  );
}
