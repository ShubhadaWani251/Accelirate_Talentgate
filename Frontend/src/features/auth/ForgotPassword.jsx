import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as yup from 'yup';
import { useNavigate, Link } from 'react-router-dom';
import * as authApi from '../../api/authApi';
import BrandHeader from '../../components/layout/BrandHeader';
import BrandFooter from '../../components/layout/BrandFooter';
import { ButtonSpinner } from '../../components/loading/Spinner';

// Shape only - is this a well-formed email - matching Login's schema exactly.
//
// It used to also require the address to end in "@accelirate.com". That was a hardcoded copy of
// a value the server reads from CORPORATE_EMAIL_DOMAIN, which is a comma-separated LIST: a staff
// account on any second configured domain could log in (Login never had this check) but was
// refused a password reset by this form, before the request even left the browser. One screen
// enforcing a stale guess at another screen's rule is worse than not checking at all, so the
// domain decision now belongs solely to the server.
//
// Nothing is lost by dropping it: ForgotPasswordView answers a non-corporate or unregistered
// address with a plain "No account found for this email address.", which this form surfaces as
// serverError. (It deliberately does reveal that, per an earlier product decision - so there is
// no anti-enumeration property here for a client-side check to have been protecting.)
const schema = yup.object({
  email: yup
    .string()
    .email('Enter a valid email')
    .required('Corporate email is required'),
});

export default function ForgotPassword() {
  const navigate = useNavigate();
  const [serverError, setServerError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm({ resolver: yupResolver(schema) });

  async function onSubmit(values) {
    setServerError('');
    setSubmitting(true);
    try {
      await authApi.forgotPassword(values.email);
      navigate('/verify-otp', { state: { email: values.email } });
    } catch (err) {
      setServerError(err.response?.data?.detail || 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="app-shell">
      <BrandHeader />
      <div className="auth-shell">
        <div className="auth-card">
          <h3>Forgot Password</h3>
          <div className="auth-sub">Enter your corporate email and we'll send you a one-time code.</div>

          {serverError && <div className="alert error">{serverError}</div>}

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
            <button className="btn primary block" type="submit" disabled={submitting}>
              <ButtonSpinner loading={submitting}>Send OTP</ButtonSpinner>
            </button>
          </form>

          <Link to="/login" className="link-text" style={{ marginTop: 14, display: 'inline-block' }}>
            Back to Login
          </Link>
        </div>
      </div>
      <BrandFooter />
    </div>
  );
}
