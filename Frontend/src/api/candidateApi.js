import axiosClient from './axiosClient';

export const listCandidates = (filters = {}) => {
  const params = {};
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined) params[key] = value;
  });
  return axiosClient.get('/candidates/', { params }).then((r) => r.data);
};

export const getCandidate = (id) => axiosClient.get(`/candidates/${id}/`).then((r) => r.data);

export const updateCandidate = (id, payload) =>
  axiosClient.patch(`/candidates/${id}/`, payload).then((r) => r.data);

export const resendInvite = (id) => axiosClient.post(`/candidates/${id}/resend-invite/`).then((r) => r.data);

export const notifyCandidates = (candidateIds, subject, message) =>
  axiosClient
    .post('/candidates/notify/', { candidate_ids: candidateIds, subject, message })
    .then((r) => r.data);

// Same authenticated-blob-download pattern as batchApi.downloadTemplate.
export const exportCandidates = async ({ from, to, batchId } = {}) => {
  const params = {};
  if (from) params.from = from;
  if (to) params.to = to;
  if (batchId) params.batch_id = batchId;
  const response = await axiosClient.get('/candidates/export/', { params, responseType: 'blob' });
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'candidates_export.xlsx';
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};
