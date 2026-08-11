import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as yup from 'yup';
import { useNavigate, Link } from 'react-router-dom';
import { useDispatch } from 'react-redux';
import { credentialsReceived } from './authSlice';
import * as authApi from '../../api/authApi';
import BrandHeader from '../../components/layout/BrandHeader';
import BrandFooter from '../../components/layout/BrandFooter';
import PasswordInput from '../../components/common/PasswordInput';

const schema = yup.object({
  email: yup.string().email('Enter a valid email').required('Corporate email is required'),
  password: yup.string().required('Password is required'),
});

export default function Login() {
  const dispatch = useDispatch();
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
      const data = await authApi.login(values.email, values.password);
      dispatch(credentialsReceived(data));
      const dest = data.user.role_code === 'admin' ? '/admin/dashboard' : '/ta/dashboard';
      navigate(dest, { replace: true });
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
          <h3>Administrator / Staffing User Login</h3>
          <div className="auth-sub">Role is resolved automatically from your account.</div>

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
            <div className="field">
              <label htmlFor="password">Password</label>
              <PasswordInput
                id="password"
                className={errors.password ? 'has-error' : ''}
                {...register('password')}
              />
              {errors.password && <div className="field-error">{errors.password.message}</div>}
            </div>
            <button className="btn primary" type="submit" disabled={submitting}>
              {submitting ? 'Logging in…' : 'Log In'}
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
