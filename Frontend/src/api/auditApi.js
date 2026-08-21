import axiosClient from './axiosClient';

// Read-only. AuditLog is append-only on the server and there is deliberately no write endpoint -
// a log an administrator can edit is not evidence of anything.

export const listAuditLogs = (filters = {}, page = 1) => {
  const params = new URLSearchParams();
  // Empty values are dropped rather than sent as `?user=`: the backend treats a blank filter as
  // "no filter" anyway, and omitting them keeps the URL readable when debugging.
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined) params.set(key, value);
  });
  params.set('page', page);
  return axiosClient.get(`/audit-logs/?${params.toString()}`).then((r) => r.data);
};

export const getAuditFilterOptions = () =>
  axiosClient.get('/audit-logs/filters/').then((r) => r.data);
