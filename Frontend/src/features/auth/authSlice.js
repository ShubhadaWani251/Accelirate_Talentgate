import { createSlice } from '@reduxjs/toolkit';

// accessToken lives only in memory (Redux state, never persisted to localStorage/sessionStorage) -
// the app handles PII (Aadhaar, exam data), so a stolen XSS payload shouldn't be able to read a
// long-lived token from storage. Session survival across a page refresh comes from the httpOnly
// refresh_token cookie via a silent /auth/refresh/ call on boot (see AppRouter / main.jsx).

// A plain UX marker, NOT a credential - nothing about it is sensitive or lets anyone
// authenticate. Its only job: let AppRouter's silent boot-time refresh tell "this browser has
// never logged in" (say nothing on failure) apart from "this browser WAS logged in, the
// session's just gone now" (show "Session expired. Please log in again.") - a distinction the
// backend deliberately no longer makes either (see api/views/auth.RefreshView), since a missing
// cookie and an invalid one are the same lived experience from there.
const HAD_SESSION_KEY = 'talentgate_had_session';

export function hadSessionBefore() {
  try {
    return localStorage.getItem(HAD_SESSION_KEY) === '1';
  } catch {
    return false; // private-browsing/storage-blocked: never warn rather than risk a false one
  }
}

function rememberSession(had) {
  try {
    if (had) localStorage.setItem(HAD_SESSION_KEY, '1');
    else localStorage.removeItem(HAD_SESSION_KEY);
  } catch { /* private browsing or storage blocked - the marker is a nice-to-have, not required */ }
}

const authSlice = createSlice({
  name: 'auth',
  initialState: {
    accessToken: null,
    user: null,
    status: 'idle', // idle | loading | authenticated | unauthenticated
  },
  reducers: {
    credentialsReceived(state, action) {
      state.accessToken = action.payload.access_token;
      state.user = action.payload.user;
      state.status = 'authenticated';
      rememberSession(true);
    },
    sessionCleared(state) {
      state.accessToken = null;
      state.user = null;
      state.status = 'unauthenticated';
      rememberSession(false);
    },
    authCheckStarted(state) {
      state.status = 'loading';
    },
  },
});

export const { credentialsReceived, sessionCleared, authCheckStarted } = authSlice.actions;
export default authSlice.reducer;

export const selectUser = (state) => state.auth.user;
export const selectAccessToken = (state) => state.auth.accessToken;
export const selectAuthStatus = (state) => state.auth.status;
export const selectRoleCode = (state) => state.auth.user?.role_code ?? null;
