import { Outlet } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { selectRoleCode } from '../../features/auth/authSlice';
import BrandHeader from './BrandHeader';
import BrandFooter from './BrandFooter';
import AppNav from './AppNav';

export default function ProtectedLayout() {
  const roleCode = useSelector(selectRoleCode);

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
