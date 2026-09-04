import axios from 'axios';

// Exported (not just used locally) so features/exam/seb/sebLaunch.js can build the SEB config
// download/launch URLs from the same origin this client already talks to, rather than
// recomputing - and potentially drifting from - the dev-vs-deployed logic a second time.
export const baseURL = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api';

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
