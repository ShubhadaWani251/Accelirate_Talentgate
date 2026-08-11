import axios from 'axios';

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

const axiosClient = axios.create({
  baseURL,
  withCredentials: true, // send/receive the httpOnly refresh_token cookie
});

// Set by the store on boot to avoid a circular import between the client and the slice.
let getAccessToken = () => null;
let onAuthExpired = () => {};

export function configureAxiosAuth({ getAccessToken: getter, onAuthExpired: expiredHandler }) {
  getAccessToken = getter;
  onAuthExpired = expiredHandler;
}

axiosClient.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

let refreshPromise = null;

axiosClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { config, response } = error;
    const isAuthEndpoint = config?.url?.includes('/auth/login') || config?.url?.includes('/auth/refresh');

    if (response?.status === 401 && !config._retried && !isAuthEndpoint) {
      config._retried = true;
      try {
        if (!refreshPromise) {
          refreshPromise = axiosClient.post('/auth/refresh/').finally(() => {
            refreshPromise = null;
          });
        }
        const { data } = await refreshPromise;
        onAuthExpired(null, data);
        config.headers.Authorization = `Bearer ${data.access_token}`;
        return axiosClient(config);
      } catch (refreshError) {
        onAuthExpired(refreshError);
        return Promise.reject(error);
      }
    }
    return Promise.reject(error);
  }
);

export default axiosClient;
