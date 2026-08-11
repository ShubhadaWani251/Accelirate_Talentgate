import { useState, useRef, useEffect } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as yup from 'yup';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import toast from 'react-hot-toast';
import * as authApi from '../../api/authApi';
import BrandHeader from '../../components/layout/BrandHeader';
import BrandFooter from '../../components/layout/BrandFooter';
import PasswordInput from '../../components/common/PasswordInput';
import { extractErrorMessage, passwordSchema, PASSWORD_HINT } from '../../utils/passwordSchema';

const RESEND_COOLDOWN_SECONDS = 60;

const schema = yup.object({
  new_password: passwordSchema,
  confirm_password: yup
    .string()
    .oneOf([yup.ref('new_password')], 'Passwords do not match')
    .required('Please confirm your new password'),
});

export default function OtpVerification() {
  const navigate = useNavigate();
  const location = useLocation();
  const email = location.state?.email;

  const [digits, setDigits] = useState(Array(6).fill(''));
  const [otpError, setOtpError] = useState('');
  const [serverError, setServerError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [cooldown, setCooldown] = useState(RESEND_COOLDOWN_SECONDS);
  const inputRefs = useRef([]);

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm({ resolver: yupResolver(schema) });

  useEffect(() => {
    if (!email) {
      navigate('/forgot-password', { replace: true });
    }
  }, [email, navigate]);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  function handleDigitChange(index, value) {
    const clean = value.replace(/\D/g, '').slice(-1);
    const next = [...digits];
    next[index] = clean;
    setDigits(next);
    if (clean && index < 5) inputRefs.current[index + 1]?.focus();
  }

  function handleDigitKeyDown(index, e) {
    if (e.key === 'Backspace' && !digits[index] && index > 0) {
      inputRefs.current[index - 1]?.focus();
    }
  }

  async function handleResend() {
    try {
      const res = await authApi.resendOtp(email);
      toast.success(res.detail || 'A new code has been sent.');
      setCooldown(RESEND_COOLDOWN_SECONDS);
    } catch (err) {
      const retryAfter = err.response?.data?.retry_after_seconds;
      if (retryAfter) setCooldown(retryAfter);
      toast.error(err.response?.data?.detail || 'Could not resend the code.');
    }
  }

  async function onSubmit(values) {
    const otp = digits.join('');
    setOtpError('');
    setServerError('');
    if (otp.length !== 6) {
      setOtpError('Enter the full 6-digit code.');
      return;
    }
    setSubmitting(true);
    try {
      await authApi.verifyOtpReset(email, otp, values.new_password, values.confirm_password);
      toast.success('Password reset. Please log in.');
      navigate('/login', { replace: true });
    } catch (err) {
      setServerError(extractErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (!email) return null;

  return (
    <div className="app-shell">
      <BrandHeader />
      <div className="auth-shell">
        <div className="auth-card">
          <h3>OTP Verification</h3>
          <div className="auth-sub">
            A 6-digit code was sent to <strong>{email}</strong>. It's valid for 10 minutes.
          </div>

          {serverError && <div className="alert error">{serverError}</div>}

          <form onSubmit={handleSubmit(onSubmit)} noValidate>
            <div className="field">
              <label>Enter Code</label>
              <div className="otp-boxes">
                {digits.map((d, i) => (
                  <input
                    key={i}
                    ref={(el) => (inputRefs.current[i] = el)}
                    value={d}
                    onChange={(e) => handleDigitChange(i, e.target.value)}
                    onKeyDown={(e) => handleDigitKeyDown(i, e)}
                    inputMode="numeric"
                    maxLength={1}
                  />
                ))}
              </div>
              {otpError && <div className="field-error">{otpError}</div>}
            </div>

            <div className="resend-row">
              <span>{cooldown > 0 ? `Resend OTP (00:${String(cooldown).padStart(2, '0')})` : ''}</span>
              <button
                type="button"
                className="link-text"
                onClick={handleResend}
                disabled={cooldown > 0}
                style={{ opacity: cooldown > 0 ? 0.5 : 1 }}
              >
                Resend OTP
              </button>
            </div>

            <div className="field" style={{ marginTop: 12 }}>
              <label htmlFor="new_password">New Password</label>
              <PasswordInput
                id="new_password"
                className={errors.new_password ? 'has-error' : ''}
                {...register('new_password')}
              />
              {errors.new_password ? (
                <div className="field-error">{errors.new_password.message}</div>
              ) : (
                <div className="field-hint">{PASSWORD_HINT}</div>
              )}
            </div>
            <div className="field">
              <label htmlFor="confirm_password">Confirm New Password</label>
              <PasswordInput
                id="confirm_password"
                className={errors.confirm_password ? 'has-error' : ''}
                {...register('confirm_password')}
              />
              {errors.confirm_password && <div className="field-error">{errors.confirm_password.message}</div>}
            </div>

            <button className="btn primary" type="submit" disabled={submitting}>
              {submitting ? 'Verifying…' : 'Verify & Reset Password'}
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
