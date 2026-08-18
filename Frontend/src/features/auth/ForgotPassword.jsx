import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as yup from 'yup';
import { useNavigate, Link } from 'react-router-dom';
import * as authApi from '../../api/authApi';
import BrandHeader from '../../components/layout/BrandHeader';
import BrandFooter from '../../components/layout/BrandFooter';

// Catches obvious mistakes (wrong domain, typos) before hitting the network. Deliberately does
// NOT check whether the email is actually registered - the backend (ForgotPasswordView) always
// returns the same generic response either way, so an attacker can't use this form to find out
// which corporate accounts exist. This is a UX improvement, not a security boundary.
const schema = yup.object({
  email: yup
    .string()
    .email('Enter a valid email')
    .required('Corporate email is required')
    .test('corporate-domain', 'Must be an @accelirate.com email address', (value) =>
      !value || value.toLowerCase().endsWith('@accelirate.com')
    ),
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
              {submitting ? 'Sending…' : 'Send OTP'}
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
