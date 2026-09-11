import { useCallback } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { sessionCleared, selectUser } from './authSlice';
import * as authApi from '../../api/authApi';

/**
 * Ends the current staff/admin session: revokes the refresh token server-side (best-effort - the
 * client-side session is cleared regardless of whether this call succeeds, same as the original
 * inline handler in AppNav.jsx), then lands on the Signed Out screen.
 *
 * Deliberately a real browser navigation (window.location.assign), not React Router's navigate():
 * this was originally an SPA transition, but that raced ProtectedRoute's own redirect - the
 * instant `status` flips to 'unauthenticated', ProtectedRoute re-renders and, seeing itself still
 * matched against the OLD (still-protected) path for one more render because React Router's own
 * location hadn't yet caught up to the navigate() call, fires its own <Navigate to="/login"> and
 * wins the race - confirmed live (repeatedly) landing on /login instead of /logged-out. A full
 * navigation sidesteps this entirely: it tears down the whole SPA and starts fresh at the new
 * URL, so there is no ProtectedRoute left to race against by definition. `reason`/`roleCode`
 * travel as query params rather than router state for the same reason - there is no SPA
 * navigation left to carry state through.
 *
 * Shared by the manual Logout button (AppNav.jsx) and the idle-timeout auto-logout
 * (useIdleLogout.js, mounted in ProtectedLayout.jsx) so both go through exactly one code path.
 */
export default function useLogout() {
  const dispatch = useDispatch();
  const user = useSelector(selectUser);

  return useCallback(async (reason) => {
    try {
      await authApi.logout();
    } catch {
      // proceed to clear client-side session regardless
    }
    // Capture the role before the store is cleared so the Signed Out screen can name the
    // console the user just left, per the wireframe.
    const roleCode = user?.role_code;
    // Clears the "had a session" marker (see hadSessionBefore's own comment) - the Redux state
    // itself is about to be torn down by the navigation below regardless, but this side effect
    // persists in localStorage, so the fresh app instance at /logged-out doesn't mistake its own
    // now-expected refresh failure for an involuntary session loss and show a stray "Session
    // expired" toast on top of the Signed Out screen.
    dispatch(sessionCleared());
    const params = new URLSearchParams();
    if (roleCode) params.set('role', roleCode);
    if (reason) params.set('reason', reason);
    const query = params.toString();
    window.location.assign(`/logged-out${query ? `?${query}` : ''}`);
  }, [dispatch, user]);
}
