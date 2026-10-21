import { useSelector } from 'react-redux';
import { selectUser } from '../../features/auth/authSlice';
import { initials } from './initials';

const ROLE_LABELS = { admin: 'Administrator', ta: 'Staffing User' };

// Who is signed in, in the top bar - the first place a reader looks for it.
// Rendered only by ProtectedLayout, as BrandHeader's optional right-hand slot: the same header
// is used by the candidate exam portal and by the login and legal pages, none of which have an
// account to show.
//
// Deliberately not a dropdown, and deliberately no Logout button. The sidebar's account card
// owns Profile, Reset Password and Logout; a second control for any of them here would be two
// controls with one job. This is a label, not a menu.
export default function HeaderAccount() {
  const user = useSelector(selectUser);

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
    </div>
  );
}
