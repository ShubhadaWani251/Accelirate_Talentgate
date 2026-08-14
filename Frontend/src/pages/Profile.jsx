import { useEffect, useState } from 'react';
import { useLocation } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { yupResolver } from '@hookform/resolvers/yup';
import * as yup from 'yup';
import toast from 'react-hot-toast';
import { useDispatch, useSelector } from 'react-redux';
import { credentialsReceived, selectUser } from '../features/auth/authSlice';
import * as authApi from '../api/authApi';
import PasswordInput from '../components/common/PasswordInput';
import { extractErrorMessage, passwordSchema, PASSWORD_HINT } from '../utils/passwordSchema';

const schema = yup.object({
  current_password: yup.string().required('Current password is required'),
  new_password: passwordSchema,
  confirm_password: yup
    .string()
    .oneOf([yup.ref('new_password')], 'Passwords do not match')
    .required('Please confirm your new password'),
});

export default function Profile() {
  const user = useSelector(selectUser);
  const dispatch = useDispatch();
  const { hash } = useLocation();
  const [submitting, setSubmitting] = useState(false);

  // React Router doesn't scroll to #fragments on its own, so the navbar's "Reset Password"
  // menu item would otherwise just land at the top of the page like plain "Profile".
  useEffect(() => {
    if (!hash) return;
    document.querySelector(hash)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, [hash]);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm({ resolver: yupResolver(schema) });

  const ROLE_LABELS = { admin: 'Administrator', ta: 'Staffing User' };

  async function onSubmit(values) {
    setSubmitting(true);
    try {
      const data = await authApi.changePassword(
        values.current_password,
        values.new_password,
        values.confirm_password
      );
      // The backend reissues tokens on password change (old ones are invalidated
      // server-side) - swap them into state now or this session's next request 401s.
      dispatch(credentialsReceived(data));
      toast.success('Password updated.');
      reset();
    } catch (err) {
      toast.error(extractErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ maxWidth: 460 }}>
      <h3>My Profile</h3>

      <div className="card">
        <div className="box-label">Account Details</div>
        <div className="field">
          <label>Name</label>
          <input value={`${user?.first_name || ''} ${user?.last_name || ''}`} disabled />
        </div>
        <div className="field">
          <label>Corporate Email</label>
          <input value={user?.email || ''} disabled />
        </div>
        <div className="field">
          <label>Role</label>
          <input value={ROLE_LABELS[user?.role_code] || user?.role_code || ''} disabled />
        </div>
      </div>

      {/* Anchor target for the navbar's "Reset Password" menu item. */}
      <div className="card" id="reset-password">
        <div className="box-label">Reset Password</div>
        <form onSubmit={handleSubmit(onSubmit)} noValidate>
          <div className="field">
            <label htmlFor="current_password">Current Password</label>
            <PasswordInput
              id="current_password"
              className={errors.current_password ? 'has-error' : ''}
              {...register('current_password')}
            />
            {errors.current_password && <div className="field-error">{errors.current_password.message}</div>}
          </div>
          <div className="field">
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
            {submitting ? 'Updating…' : 'Update Password'}
          </button>
        </form>
      </div>
    </div>
  );
}
