import axiosClient from './axiosClient';

function downloadBlob(data, filename) {
  const url = window.URL.createObjectURL(new Blob([data]));
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

// Returns the paginated envelope {count, next, previous, results} - pass `page` (and optionally
// `page_size`) as one of the filter keys to move between pages, same as any other filter.
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

export const getCandidateHistory = (id) =>
  axiosClient.get(`/candidates/${id}/history/`).then((r) => r.data);

export const listNotificationTemplates = () =>
  axiosClient.get('/candidates/notify/templates/').then((r) => r.data);

// `template` is the approved-template key; `message` is only sent when the TA has edited the
// body, in which case it overrides the template's own copy server-side.
export const notifyCandidates = (candidateIds, { template, message, subject } = {}) =>
  axiosClient
    .post('/candidates/notify/', { candidate_ids: candidateIds, template, message, subject })
    .then((r) => r.data);

// The certification copy is fixed server-side - only the two links travel from the UI.
// The two UiPath course links are part of the approved copy server-side, so the only
// per-send value is the completion deadline.
export const sendCertificationEmail = (candidateIds, { deadline }) =>
  axiosClient
    .post('/candidates/send-certification/', {
      candidate_ids: candidateIds, deadline,
    })
    .then((r) => r.data);

// Same authenticated-blob-download pattern as batchApi.downloadTemplate.
export const exportCandidates = async ({ from, to, batchId } = {}) => {
  const params = {};
  if (from) params.from = from;
  if (to) params.to = to;
  if (batchId) params.batch_id = batchId;
  const response = await axiosClient.get('/candidates/export/', { params, responseType: 'blob' });
  downloadBlob(response.data, 'candidates_export.xlsx');
};

export const downloadEvidenceZip = async (id) => {
  const response = await axiosClient.get(`/candidates/${id}/evidence.zip`, { responseType: 'blob' });
  downloadBlob(response.data, `candidate_${id}_evidence.zip`);
};
