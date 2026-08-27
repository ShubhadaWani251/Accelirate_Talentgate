import axiosClient from './axiosClient';

export const login = (email, password) =>
  axiosClient.post('/auth/login/', { email, password }).then((r) => r.data);

export const logout = () => axiosClient.post('/auth/logout/').then((r) => r.data);

// Deduped so that React 18 StrictMode's double-invoke of the boot effect (mount -> unmount ->
// mount, firing this twice almost synchronously) doesn't send two concurrent refresh requests.
// The refresh token rotates on every successful call, so a second call still carrying the
// now-stale cookie would otherwise 401 and wrongly look like an invalid session.
let refreshInFlight = null;

export const refresh = () => {
  if (!refreshInFlight) {
    refreshInFlight = axiosClient
      .post('/auth/refresh/')
      .then((r) => r.data)
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
};

export const me = () => axiosClient.get('/auth/me/').then((r) => r.data);

export const forgotPassword = (email) =>
  axiosClient.post('/auth/forgot-password/', { email }).then((r) => r.data);

export const resendOtp = (email) =>
  axiosClient.post('/auth/resend-otp/', { email }).then((r) => r.data);

export const verifyOtpReset = (email, otp, newPassword, confirmPassword) =>
  axiosClient
    .post('/auth/verify-otp/', {
      email,
      otp,
      new_password: newPassword,
      confirm_password: confirmPassword,
    })
    .then((r) => r.data);

export const changePassword = (currentPassword, newPassword, confirmPassword) =>
  axiosClient
    .post('/auth/change-password/', {
      current_password: currentPassword,
      new_password: newPassword,
      confirm_password: confirmPassword,
    })
    .then((r) => r.data);
