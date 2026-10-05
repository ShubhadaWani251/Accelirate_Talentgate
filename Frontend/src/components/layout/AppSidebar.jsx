import { useState, useRef, useEffect } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { useSelector } from 'react-redux';
import {
  LuArrowLeft, LuBookOpen, LuChevronRight, LuDownload, LuLayoutDashboard, LuLogOut,
  LuPlus, LuScrollText, LuSettings, LuUserCog, LuUsers,
} from 'react-icons/lu';
import { selectUser } from '../../features/auth/authSlice';
import useLogout from '../../features/auth/useLogout';
import { initials } from './initials';
import ExportModal from '../../features/candidates/ExportModal';

// Same destinations the horizontal nav carried, in the same order and with the same role split -
// this replaced how the links are laid out, not which ones exist. Admin keeps Audit Log; the TA
// list is deliberately the shorter one. Icons are Lucide via react-icons/lu, which is what the
// brand guidelines name and what is already installed; no new dependency was added for this.
const NAV_LINKS = {
  admin: [
    { label: 'Dashboard', to: '/admin/dashboard', Icon: LuLayoutDashboard },
    { label: 'All Candidates', to: '/candidates', Icon: LuUsers },
    { label: 'Question Bank', to: '/admin/question-bank', Icon: LuBookOpen },
    { label: 'Users', to: '/admin/users', Icon: LuUserCog },
    // Admin only - deliberately absent from the ta list below.
    { label: 'Audit Log', to: '/admin/audit-logs', Icon: LuScrollText },
  ],
  ta: [
    { label: 'Dashboard', to: '/ta/dashboard', Icon: LuLayoutDashboard },
    { label: 'All Candidates', to: '/candidates', Icon: LuUsers },
  ],
};

const ROLE_HOME = { admin: '/admin/dashboard', ta: '/ta/dashboard' };
const ROLE_LABELS = { admin: 'Administrator', ta: 'Staffing User' };

// The dashboard's action row, repeated here so it is reachable from every screen rather than
// only from the dashboard. Deliberately NOT a fourth entry for "View All Candidates": that is
// the All Candidates link above, and listing one destination twice makes a reader wonder what
// the difference is.
//
// adminOnly mirrors the dashboard's own gate on Configure Default Batch - it sets what EVERY new
// batch is created with, org-wide, which is a wider blast radius than one TA's own work.
const ACTIONS = [
  { label: 'Create Batch', to: '/batches/new', Icon: LuPlus },
  { label: 'Export Candidates', action: 'export', Icon: LuDownload },
  { label: 'Default Batch Config', to: '/admin/default-batch-config', Icon: LuSettings,
    adminOnly: true },
];

// Renders the whole body row - sidebar beside the page - rather than just the sidebar, because
// the Back/Menu strip belongs above the page content and the open/closed state is shared between
// the two. Keeping both here keeps that state local instead of threading it through the layout.
// navOpen/onCloseNav are owned by ProtectedLayout, because the toggle that drives them lives in
// the brand header - a sibling of this component, not a descendant. Below 900px "open" means the
// sidebar slides over the page (see theme.css); above it, open or closed is simply whether the
// column is there, since a fixed 232px column leaves too little room for a data table on a phone
// but is worth its width on a monitor.
export default function AppSidebar({ children, navOpen = true, onCloseNav }) {
  const user = useSelector(selectUser);
  const navigate = useNavigate();
  const logout = useLogout();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  // The export modal is rendered here rather than reached through the dashboard, so the action
  // works from whichever screen the sidebar is on. ExportModal is self-contained - omitting
  // batchId is what makes it export every candidate rather than one batch's.
  const [exportOpen, setExportOpen] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    function onClickOutside(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
    }
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, []);

  // Close the slide-over on navigation, otherwise it stays open covering the page just asked
  // for. Guarded by the breakpoint, which matters now the state is shared with the header's
  // toggle: on a desktop the sidebar is not covering anything, and collapsing it on every click
  // would make the navigation destroy itself each time it was used.
  useEffect(() => {
    if (!window.matchMedia('(min-width: 901px)').matches) onCloseNav?.();
  }, [location.pathname, onCloseNav]);

  const isAdmin = user?.role_code === 'admin';
  const links = NAV_LINKS[user?.role_code] || [];
  const home = ROLE_HOME[user?.role_code] || '/';
  const atHome = location.pathname === home;

  // react-router stamps an incrementing `idx` onto history.state for every entry it pushes.
  // idx === 0 means this is the first entry in the session's history, so navigate(-1) would
  // leave the app entirely (or dead-end on a blank page) - fall back to Home in that case.
  function handleBack() {
    const hasPrevious = (window.history.state?.idx ?? 0) > 0;
    if (!hasPrevious) navigate(home);
    else navigate(-1);
  }

  return (
    <div className="app-body">
      {/* Dims and closes the slide-over. Rendered only while open so it never intercepts a click
          on the desktop layout, where the sidebar is always visible and never overlays anything. */}
      {navOpen && (
        <button
          type="button"
          className="sidebar-scrim"
          aria-label="Close navigation menu"
          onClick={onCloseNav}
        />
      )}

      <aside id="app-sidebar" className={`app-sidebar${navOpen ? ' is-open' : ''}`}>
        <nav className="sidebar-links" aria-label="Main">
          {links.map(({ label, to, Icon }) => (
            <Link
              key={label}
              to={to}
              className={`sidebar-link${location.pathname === to ? ' current' : ''}`}
              aria-current={location.pathname === to ? 'page' : undefined}
            >
              <Icon className="sidebar-icon" aria-hidden="true" />
              <span>{label}</span>
            </Link>
          ))}
        </nav>

        {/* Separated from the links above by a rule and a label, because these DO something
            rather than go somewhere - a reader scanning for "where am I" should not have to
            read past them. */}
        <div className="sidebar-actions">
          <div className="sidebar-group-label">Quick Actions</div>
          {ACTIONS.filter((a) => !a.adminOnly || isAdmin).map(({ label, to, action, Icon }) => (
            // Branching on `action` rather than on the absence of `to`, so an entry that opens
            // something in place is marked as one rather than inferred from a missing field.
            action === 'export' ? (
              <button
                key={label}
                type="button"
                className="sidebar-action"
                onClick={() => { onCloseNav?.(); setExportOpen(true); }}
              >
                <Icon className="sidebar-icon" aria-hidden="true" /><span>{label}</span>
              </button>
            ) : (
              <Link key={label} to={to} className="sidebar-action">
                <Icon className="sidebar-icon" aria-hidden="true" /><span>{label}</span>
              </Link>
            )
          ))}
        </div>

        {/* Pinned to the bottom. The account is the one thing here that is about who you are
            rather than where you are going, so it is separated from the links above it. */}
        <div className="sidebar-user" ref={menuRef}>
          {menuOpen && (
            <div className="sidebar-user-menu">
              <button className="pitem" onClick={() => { setMenuOpen(false); navigate('/profile'); }}>
                Profile
              </button>
              <button
                className="pitem"
                onClick={() => { setMenuOpen(false); navigate('/profile#reset-password'); }}
              >
                Reset Password
              </button>
              <button className="pitem logout" onClick={() => logout()}>Logout</button>
            </div>
          )}
          <button
            type="button"
            className="sidebar-user-trigger"
            onClick={() => setMenuOpen((o) => !o)}
            aria-expanded={menuOpen}
            aria-label="Account menu"
          >
            <span className="avatar">{initials(user)}</span>
            <span className="sidebar-user-text">
              <span className="sidebar-user-name">{user?.first_name} {user?.last_name}</span>
              <span className="sidebar-user-role">
                {ROLE_LABELS[user?.role_code] || user?.role_code}
              </span>
            </span>
            <LuChevronRight className="sidebar-user-chevron" aria-hidden="true" />
          </button>
          {/* Kept as its own control beside the menu, not only inside it: logging out should
              never require opening a menu first. */}
          <button className="btn sidebar-logout" onClick={() => logout()}>
            <LuLogOut aria-hidden="true" /> Logout
          </button>
        </div>
      </aside>

      {exportOpen && <ExportModal onClose={() => setExportOpen(false)} />}

      <div className="page-col">
        {/* A thin strip above the page rather than inside the sidebar: Back is about the content
            below it, not about navigation, and it only appears on pages with somewhere to go
            back to. It used to carry a Menu button too; that moved to the brand header, where it
            sits beside the logo and is reachable at every width rather than only under 900px. */}
        <div className="page-topbar">
          {!atHome && (
            <button className="btn small nav-back" onClick={handleBack}>
              <LuArrowLeft aria-hidden="true" /> Back
            </button>
          )}
        </div>
        <main className="page-body">{children}</main>
      </div>
    </div>
  );
}
