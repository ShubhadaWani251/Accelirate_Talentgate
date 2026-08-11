import { configureStore } from '@reduxjs/toolkit';
import authReducer from '../features/auth/authSlice';
import { configureAxiosAuth } from '../api/axiosClient';
import { credentialsReceived, sessionCleared } from '../features/auth/authSlice';

export const store = configureStore({
  reducer: {
    auth: authReducer,
  },
});

configureAxiosAuth({
  getAccessToken: () => store.getState().auth.accessToken,
  onAuthExpired: (error, refreshedData) => {
    if (refreshedData) {
      store.dispatch(credentialsReceived(refreshedData));
    } else {
      store.dispatch(sessionCleared());
    }
  },
});

export default store;
