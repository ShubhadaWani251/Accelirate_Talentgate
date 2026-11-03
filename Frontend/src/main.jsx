import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { Provider } from 'react-redux';
import { Toaster } from 'react-hot-toast';
import './index.css';
import store from './app/store';
import AppRouter from './routes/AppRouter';

// Microsoft sign-in redirects its popup back to THIS origin carrying the auth response in the
// URL fragment, and MSAL in the window that opened the popup reads it from there.
//
// Booting the app in that popup destroys it. AppRouter sends anyone not signed in to /login
// (routes/AppRouter.jsx), and that navigation drops the fragment before MSAL ever looks - so
// the popup sits on a second copy of the login screen, the opener waits for a response that no
// longer exists, and the sign-in silently never completes. That is the bug this guard fixes,
// and it is not hypothetical: it is what the popup did.
//
// Detected rather than routed around because the alternative - pointing redirectUri at a blank
// page like /blank.html - means re-registering a different URI in Entra for every environment,
// and the registered origins are hard-won here. Nothing about that approach is better; it just
// moves where the "do not load the app" decision is written down.
//
// Narrow on purpose: an opener AND a state parameter AND an outcome. Anything less would make
// a stray fragment on a normally-opened window render a blank page instead of the app.
const hash = window.location.hash;
const isSignInPopupResponse = Boolean(window.opener)
  && hash.includes('state=')
  && (hash.includes('code=') || hash.includes('error='));

if (isSignInPopupResponse) {
  // Deliberately renders no app and navigates nowhere: the fragment above has to survive
  // untouched until the opener reads it and closes this window. The text is only for the
  // moment it is visible, and for the case where the opener never does close it.
  document.getElementById('root').textContent = 'Completing sign-in…';
} else {
  createRoot(document.getElementById('root')).render(
    <StrictMode>
      <Provider store={store}>
        <Toaster position="top-right" />
        <AppRouter />
      </Provider>
    </StrictMode>,
  );
}
