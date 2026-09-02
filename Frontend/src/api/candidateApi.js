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

// linkWindow ({ link_valid_from, link_valid_until } in ISO, both optional) gives THIS
// invitation its own valid-from/until, independent of the batch's - which is locked to its
// original dates once the batch leaves Draft, specifically so resending to one candidate can't
// shift the window for everyone else in it. Omit to inherit the batch's current window.
export const resendInvite = (id, linkWindow = {}) =>
  axiosClient.post(`/candidates/${id}/resend-invite/`, linkWindow).then((r) => r.data);

// Issues a FRESH link to each selected candidate, all sharing the one linkWindow given. Not the
// same as the upload wizard's send-invites step, which only covers candidates awaiting their
// first invite - this one always mints a new token, which is what someone whose link expired
// actually needs.
export const resendInvitesBulk = (candidateIds, linkWindow = {}) =>
  axiosClient.post('/candidates/resend-invite/', { candidate_ids: candidateIds, ...linkWindow })
    .then((r) => r.data);

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
