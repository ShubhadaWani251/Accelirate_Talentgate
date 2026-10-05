import { useCallback } from 'react';
import { Outlet } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { selectRoleCode } from '../../features/auth/authSlice';
import useLogout from '../../features/auth/useLogout';
import useIdleLogout from '../../features/auth/useIdleLogout';
import BrandHeader from './BrandHeader';
import BrandFooter from './BrandFooter';
import AppSidebar from './AppSidebar';
import HeaderAccount from './HeaderAccount';

export default function ProtectedLayout() {
  const roleCode = useSelector(selectRoleCode);
  const logout = useLogout();
  // Mounted once here, at the root of the whole protected (staff/admin) route tree - see
  // useIdleLogout's own docstring for why this must never wrap the candidate exam portal.
  const onIdle = useCallback(() => { logout('idle'); }, [logout]);
  useIdleLogout(onIdle);

  return (
    // staff-shell locks the viewport so the sidebar, header and footer stay put and only the
    // page content scrolls - see theme.css. Its own class rather than a change to .app-shell,
    // which every other page (including the candidate portal) relies on to grow taller than
    // the viewport; the exam screen solves the same problem the same way with .exam-shell.
    <div className="app-shell staff-shell">
      <BrandHeader roleCode={roleCode}>
        <HeaderAccount />
      </BrandHeader>
      {/* Sidebar beside the page rather than a bar above it. The brand header and footer stay
          full width across the top and bottom, so this row is the only part that splits - which
          also keeps BrandHeader untouched for the candidate exam portal, which renders it too
          and has no sidebar at all. */}
      <AppSidebar>
        <Outlet />
      </AppSidebar>
      <BrandFooter roleCode={roleCode} />
    </div>
  );
}
