import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Provider } from 'react-redux';
import { Toaster } from 'react-hot-toast';
import './index.css';
import store from './app/store';
import AppRouter from './routes/AppRouter';

// Microsoft sign-in used to run in a popup, and this file carried a guard that refused to boot
// the app when it detected the popup's auth response in the URL. That guard is gone with the
// popup (see features/auth/msal.js): sign-in now redirects THIS tab, so the response arrives on
// a normal page load that must boot normally. AppRouter reads it during its auth check.
//
// Removed rather than left in place as a no-op, because it keyed off window.opener and would
// have become a trap: any window the app happened to be opened from would have satisfied it and
// left the person on a blank "Completing sign-in…" page that nothing ever navigates away from.

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <Provider store={store}>
      <Toaster position="top-right" />
      <AppRouter />
    </Provider>
  </StrictMode>,
);
