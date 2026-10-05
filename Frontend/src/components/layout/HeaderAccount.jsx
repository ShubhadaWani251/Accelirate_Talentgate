import { useSelector } from 'react-redux';
import { LuLogOut } from 'react-icons/lu';
import { selectUser } from '../../features/auth/authSlice';
import useLogout from '../../features/auth/useLogout';
import { initials } from './initials';

const ROLE_LABELS = { admin: 'Administrator', ta: 'Staffing User' };

// Who is signed in, and the way out, in the top bar - the two places a reader looks for either.
// Rendered only by ProtectedLayout, as BrandHeader's optional right-hand slot: the same header
// is used by the candidate exam portal and by the login and legal pages, none of which have an
// account to show or a session to end.
//
// Deliberately not a dropdown. The sidebar's account card already owns Profile and Reset
// Password; repeating that menu here would give two controls the same job, and the thing worth
// having twice is the signed-in name and Logout, not a second copy of the menu behind them.
export default function HeaderAccount() {
  const user = useSelector(selectUser);
  const logout = useLogout();

  if (!user) return null;

  return (
    <div className="header-account">
      <span className="header-account-who">
        <span className="avatar header-avatar">{initials(user)}</span>
        <span className="header-account-text">
          <span className="header-account-name">{user.first_name} {user.last_name}</span>
          <span className="header-account-role">
            {ROLE_LABELS[user.role_code] || user.role_code}
          </span>
        </span>
      </span>
      <button type="button" className="btn header-logout" onClick={() => logout()}>
        <LuLogOut aria-hidden="true" /> Logout
      </button>
    </div>
  );
}
