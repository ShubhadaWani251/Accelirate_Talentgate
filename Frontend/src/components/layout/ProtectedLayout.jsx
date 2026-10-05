import { useCallback, useEffect, useState } from 'react';
import { Outlet } from 'react-router-dom';
import { useSelector } from 'react-redux';
import { selectRoleCode } from '../../features/auth/authSlice';
import useLogout from '../../features/auth/useLogout';
import useIdleLogout from '../../features/auth/useIdleLogout';
import BrandHeader from './BrandHeader';
import BrandFooter from './BrandFooter';
import AppSidebar from './AppSidebar';
import HeaderAccount from './HeaderAccount';

// Above this the sidebar sits beside the page and starts open; below it the sidebar is a
// slide-over and starts closed. Matches the breakpoint theme.css switches layouts at.
const DESKTOP = '(min-width: 901px)';

export default function ProtectedLayout() {
  const roleCode = useSelector(selectRoleCode);
  const logout = useLogout();
  // One piece of state meaning "the sidebar is showing", owned here because the brand header's
  // toggle and the sidebar itself are siblings. Its sensible DEFAULT differs by screen size -
  // open on a desktop, closed on a phone where it would otherwise cover the page on arrival -
  // so it is seeded from the viewport rather than from a constant.
  const [navOpen, setNavOpen] = useState(() => window.matchMedia(DESKTOP).matches);
  const toggleNav = useCallback(() => setNavOpen((o) => !o), []);
  // Stable identity on purpose: AppSidebar closes on navigation via an effect that depends on
  // this, so a fresh arrow each render would re-run that effect every render.
  const closeNav = useCallback(() => setNavOpen(false), []);

  // Crossing the breakpoint resets to that size's default. Without this, a sidebar left open on
  // a desktop becomes a slide-over covering the page the moment the window narrows, and one
  // closed on a phone leaves a widened window with no navigation until the user finds the
  // toggle again.
  useEffect(() => {
    const mq = window.matchMedia(DESKTOP);
    const sync = (e) => setNavOpen(e.matches);
    mq.addEventListener('change', sync);
    return () => mq.removeEventListener('change', sync);
  }, []);
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
      <BrandHeader roleCode={roleCode} onToggleNav={toggleNav} navOpen={navOpen}>
        <HeaderAccount />
      </BrandHeader>
      {/* Sidebar beside the page rather than a bar above it. The brand header and footer stay
          full width across the top and bottom, so this row is the only part that splits - which
          also keeps BrandHeader untouched for the candidate exam portal, which renders it too
          and has no sidebar at all. */}
      <AppSidebar navOpen={navOpen} onCloseNav={closeNav}>
        <Outlet />
      </AppSidebar>
      <BrandFooter roleCode={roleCode} />
    </div>
  );
}
