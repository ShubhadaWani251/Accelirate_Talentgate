import { createSlice } from '@reduxjs/toolkit';

// accessToken lives only in memory (Redux state, never persisted to localStorage/sessionStorage) -
// the app handles PII (Aadhaar, exam data), so a stolen XSS payload shouldn't be able to read a
// long-lived token from storage. Session survival across a page refresh comes from the httpOnly
// refresh_token cookie via a silent /auth/refresh/ call on boot (see AppRouter / main.jsx).
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
    },
    sessionCleared(state) {
      state.accessToken = null;
      state.user = null;
      state.status = 'unauthenticated';
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
