import axios from 'axios';

const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

// Separate instance from axiosClient.js on purpose: candidates aren't staff, there's no
// refresh cookie, and a 401 here just means "go back through /t/<token> and resume" - handled
// explicitly by the pages, not retried transparently.
const examAxiosClient = axios.create({ baseURL });

let attemptToken = null;

export function setAttemptToken(token) {
  attemptToken = token || null;
}

examAxiosClient.interceptors.request.use((config) => {
  if (attemptToken) {
    config.headers.Authorization = `Bearer ${attemptToken}`;
  }
  return config;
});

export default examAxiosClient;
