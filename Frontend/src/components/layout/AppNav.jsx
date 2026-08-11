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
    { label: 'Question Bank', to: null },
    { label: 'Users', to: null },
  ],
  ta: [
    { label: 'Dashboard', to: '/ta/dashboard' },
    { label: 'All Candidates', to: '/candidates' },
  ],
};

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
  const menuRef = useRef(null);

  useEffect(() => {
    function onClickOutside(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false);
    }
    document.addEventListener('mousedown', onClickOutside);
    return () => document.removeEventListener('mousedown', onClickOutside);
  }, []);

  const links = NAV_LINKS[user?.role_code] || [];

  async function handleLogout() {
    try {
      await authApi.logout();
    } catch {
      // proceed to clear client-side session regardless
    }
    dispatch(sessionCleared());
    navigate('/login', { replace: true });
  }

  return (
    <nav className="app-nav">
      <div className="nav-left">
        <span className="nav-brand">CEP {user?.role_code === 'admin' ? 'Administrator' : 'Staffing User'}</span>
        <div className="nav-links">
          {links.map((link) =>
            link.to ? (
              <Link key={link.label} to={link.to} style={{ textDecoration: 'none' }}>
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

      <div className="profile-wrap" ref={menuRef}>
        <button className="profile-trigger" onClick={() => setMenuOpen((o) => !o)}>
          <span className="avatar">{initials(user)}</span>
          <span>{user?.first_name} {user?.last_name}</span>
        </button>
        {menuOpen && (
          <div className="profile-menu">
            <button className="pitem" onClick={() => { setMenuOpen(false); navigate('/profile'); }}>
              Profile
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
