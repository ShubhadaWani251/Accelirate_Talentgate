import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as yup from 'yup';
import { useNavigate, Link } from 'react-router-dom';
import { useDispatch } from 'react-redux';
import { credentialsReceived } from './authSlice';
import { isSsoConfigured, startMicrosoftSignIn } from './msal';
import { describeSsoError, takeSsoError } from './ssoError';
import * as authApi from '../../api/authApi';
import BrandHeader from '../../components/layout/BrandHeader';
import BrandFooter from '../../components/layout/BrandFooter';
import PasswordInput from '../../components/common/PasswordInput';
import { ButtonSpinner } from '../../components/loading/Spinner';

const schema = yup.object({
  email: yup.string().email('Enter a valid email').required('Corporate email is required'),
  password: yup.string().required('Password is required'),
});

// Microsoft's four-square mark, inline rather than from react-icons: their brand guidelines
// require these exact four colours on a sign-in button, and a monochrome icon font cannot
// carry them. aria-hidden because the button's own text already says what it does.
function MicrosoftLogo() {
  return (
    <svg width="16" height="16" viewBox="0 0 21 21" aria-hidden="true" focusable="false">
      <rect x="1" y="1" width="9" height="9" fill="#f25022" />
      <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
      <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
      <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
    </svg>
  );
}

export default function Login() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  // Seeded from the handoff, not empty: a Microsoft sign-in that fails does so during the app
  // boot at the redirect URI, one navigation before this screen exists. takeSsoError() clears
  // it as it reads, so it shows once and does not come back on a reload. The lazy initialiser
  // matters - a bare takeSsoError() would run on every render and consume the message during
  // the first one, before React had committed anything.
  const [serverError, setServerError] = useState(takeSsoError);
  const [submitting, setSubmitting] = useState(false);
  const [ssoBusy, setSsoBusy] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm({ resolver: yupResolver(schema) });

  // Both sign-in routes end here, because they produce the same thing: the server returns an
  // identical {access_token, user} either way, so there is one place that decides what a
  // session means and where it lands.
  function onSignedIn(data) {
    dispatch(credentialsReceived(data));
    const dest = data.user.role_code === 'admin' ? '/admin/dashboard' : '/ta/dashboard';
    navigate(dest, { replace: true });
  }

  async function onSubmit(values) {
    setServerError('');
    setSubmitting(true);
    try {
      onSignedIn(await authApi.login(values.email, values.password));
    } catch (err) {
      setServerError(err.response?.data?.detail || 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  // Sends the browser to Microsoft. Nothing after the await runs on success - the page is gone,
  // and the response comes back to a fresh app boot, which finishes the job (routes/AppRouter).
  // ssoBusy is therefore left ON deliberately: the button stays disabled and spinning for the
  // moment before the navigation takes effect, which is exactly right, and a second click in
  // that window would start a second sign-in.
  async function onMicrosoftSignIn() {
    setServerError('');
    setSsoBusy(true);
    try {
      await startMicrosoftSignIn();
    } catch (err) {
      console.error('Microsoft sign-in failed', err);
      setServerError(describeSsoError(err));
      setSsoBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <BrandHeader />
      <div className="auth-shell">
        <div className="auth-card">
          <h3>Administrator / Staffing User Login</h3>
          <div className="auth-sub">Role is resolved automatically from your account.</div>

          {serverError && <div className="alert error">{serverError}</div>}

          {/* Above the form, because it is the route most people should take - and absent
              entirely where no Entra registration is configured, rather than present and
              broken. The password form below is never removed either way. */}
          {isSsoConfigured() && (
            <>
              <button
                type="button"
                className="btn block sso-btn"
                onClick={onMicrosoftSignIn}
                disabled={ssoBusy || submitting}
              >
                <ButtonSpinner loading={ssoBusy}>
                  <MicrosoftLogo /> Sign in with Microsoft
                </ButtonSpinner>
              </button>
              <div className="auth-divider"><span>or</span></div>
            </>
          )}

          <form onSubmit={handleSubmit(onSubmit)} noValidate>
            <div className="field">
              <label htmlFor="email">Corporate Email</label>
              <input
                id="email"
                type="email"
                placeholder="name@accelirate.com"
                className={errors.email ? 'has-error' : ''}
                {...register('email')}
              />
              {errors.email && <div className="field-error">{errors.email.message}</div>}
            </div>
            <div className="field">
              <label htmlFor="password">Password</label>
              <PasswordInput
                id="password"
                className={errors.password ? 'has-error' : ''}
                {...register('password')}
              />
              {errors.password && <div className="field-error">{errors.password.message}</div>}
            </div>
            <button className="btn primary block" type="submit" disabled={submitting}>
              <ButtonSpinner loading={submitting}>Log In</ButtonSpinner>
            </button>
          </form>

          <Link to="/forgot-password" className="link-text" style={{ marginTop: 14, display: 'inline-block' }}>
            Forgot password?
          </Link>
        </div>
      </div>
      <BrandFooter />
    </div>
  );
}
