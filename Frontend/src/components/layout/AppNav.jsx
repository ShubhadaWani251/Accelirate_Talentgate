import { useState, useRef, useEffect } from 'react';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import { selectUser } from '../../features/auth/authSlice';
import { sessionCleared } from '../../features/auth/authSlice';
import * as authApi from '../../api/authApi';

const NAV_LINKS = {
  admin: [
    { label: 'Dashboard', to: '/admin/dashboard' },
    { label: 'All Candidates', to: '/candidates' },
    { label: 'Question Bank', to: '/admin/question-bank' },
    { label: 'Users', to: '/admin/users' },
    // Admin only - deliberately absent from the ta list below.
    { label: 'Audit Log', to: '/admin/audit-logs' },
  ],
  ta: [
    { label: 'Dashboard', to: '/ta/dashboard' },
    { label: 'All Candidates', to: '/candidates' },
  ],
};

const ROLE_HOME = { admin: '/admin/dashboard', ta: '/ta/dashboard' };

function initials(user) {
  if (!user) return '';
  return `${user.first_name?.[0] || ''}${user.last_name?.[0] || ''}`.toUpperCase();
}

export default function AppNav() {
  const user = useSelector(selectUser);
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  // Mobile only: the nav links collapse behind a toggle below 768px (see theme.css). On desktop
  // and tablet the links are always visible and this state is simply unused.
  const [navOpen, setNavOpen] = useState(false);
  const menuRef = useRef(null);

  useEffect(() => {
    function onClickOutside(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
    }
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, []);

  const links = NAV_LINKS[user?.role_code] || [];
  const home = ROLE_HOME[user?.role_code] || '/';

  // react-router stamps an incrementing `idx` onto history.state for every entry it pushes.
  // idx === 0 means this is the first entry in the session's history, so navigate(-1) would
  // leave the app entirely (or dead-end on a blank page) - fall back to Home in that case,
  // and on the dashboard itself, where "back" has nowhere useful to go.
  function handleBack() {
    const atHome = location.pathname === home;
    const hasPrevious = (window.history.state?.idx ?? 0) > 0;
    if (atHome || !hasPrevious) navigate(home);
    else navigate(-1);
  }

  async function handleLogout() {
    try {
      await authApi.logout();
    } catch {
      // proceed to clear client-side session regardless
    }
    // Capture the role before the store is cleared so the Signed Out screen can name the
    // console the user just left, per the wireframe.
    const roleCode = user?.role_code;
    dispatch(sessionCleared());
    navigate('/logged-out', { replace: true, state: { roleCode } });
  }

  return (
    <nav className="app-nav">
      <div className="nav-left">
        <button className="btn small nav-back" onClick={handleBack}>← Back</button>
        <button className="btn small primary nav-home" onClick={() => navigate(home)}>Home</button>
        <span className="nav-brand">CEP — {user?.role_code === 'admin' ? 'Administrator' : 'Staffing User'}</span>
        {/* Visible only under 768px (CSS-driven), so desktop/tablet behaviour is unchanged. */}
        <button
          type="button"
          className="btn small nav-toggle"
          onClick={() => setNavOpen((o) => !o)}
          aria-expanded={navOpen}
          aria-controls="app-nav-links"
          aria-label={navOpen ? 'Hide navigation menu' : 'Show navigation menu'}
        >
          ☰ Menu
        </button>
        <div id="app-nav-links" className={`nav-links${navOpen ? ' is-open' : ''}`}>
          {links.map((link) =>
            link.to ? (
              // Collapse the mobile menu on navigation, otherwise it stays open over the page
              // the user just asked for.
              <Link
                key={link.label}
                to={link.to}
                style={{ textDecoration: 'none' }}
                onClick={() => setNavOpen(false)}
              >
                <span className={location.pathname === link.to ? 'current' : ''}>{link.label}</span>
              </Link>
            ) : (
              <span key={link.label} style={{ opacity: 0.4, cursor: 'not-allowed' }} title="Coming soon">
                {link.label}
              </span>
            )
          )}
        </div>
      </div>

      {/* The wireframe shows a always-visible Logout button *alongside* the profile dropdown,
          not only inside it - logging out shouldn't need a menu to be opened first. */}
      <div className="profile-wrap" ref={menuRef}>
        <button className="btn" onClick={handleLogout}>Logout</button>
        <button className="profile-trigger" onClick={() => setMenuOpen((o) => !o)}>
          <span className="avatar">{initials(user)}</span>
          {/* Hidden below 768px - the avatar still identifies the account, and the name is the
              first thing worth sacrificing for horizontal space on a phone. */}
          <span className="profile-name">{user?.first_name} {user?.last_name}</span>
        </button>
        {menuOpen && (
          <div className="profile-menu">
            <button className="pitem" onClick={() => { setMenuOpen(false); navigate('/profile'); }}>
              Profile
            </button>
            <button className="pitem" onClick={() => { setMenuOpen(false); navigate('/profile#reset-password'); }}>
              Reset Password
            </button>
            <button className="pitem logout" onClick={handleLogout}>
              Logout
            </button>
          </div>
        )}
      </div>
    </nav>
  );
}
