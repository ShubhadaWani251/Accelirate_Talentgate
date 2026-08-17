import axiosClient from './axiosClient';

// Returns the paginated envelope {count, next, previous, results} - callers that just want
// every batch for a dropdown (not a browsable list) should pass a page_size big enough to
// cover realistic batch counts in one page (e.g. { pageSize: 200 }).
//
// Drafts are excluded unless you ask for them by status: an unfinished upload has no
// candidates or results yet, so it isn't a batch anyone can act on. Pass { status: 'draft' }
// for the "Unfinished uploads" view.
export const listBatches = (search = '', { page, pageSize, status } = {}) => {
  const params = {};
  if (search) params.search = search;
  if (page) params.page = page;
  if (pageSize) params.page_size = pageSize;
  if (status) params.status = status;
  return axiosClient.get('/batches/', { params }).then((r) => r.data);
};

export const getBatch = (id) => axiosClient.get(`/batches/${id}/`).then((r) => r.data);

export const createBatch = (payload) => axiosClient.post('/batches/', payload).then((r) => r.data);

export const updateBatch = (id, payload) =>
  axiosClient.patch(`/batches/${id}/`, payload).then((r) => r.data);

// Batches are deactivated, never deleted - candidate and result history stays intact.
export const deactivateBatch = (id) =>
  axiosClient.post(`/batches/${id}/deactivate/`).then((r) => r.data);

export const getBatchDefaults = () => axiosClient.get('/batches/defaults/').then((r) => r.data);

export const saveBatchDefaults = (payload) =>
  axiosClient.put('/batches/defaults/', payload).then((r) => r.data);

// The endpoint is authenticated like everything else, so a plain <a href> (no
// Authorization header) would 401 - fetch through axios and trigger the download
// from the resulting blob instead.
export const downloadTemplate = async () => {
  const response = await axiosClient.get('/batches/template/', { responseType: 'blob' });
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'candidate_upload_template.xlsx';
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};

export const uploadCandidates = (batchId, file, coolingOffMonths) => {
  const form = new FormData();
  form.append('file', file);
  if (coolingOffMonths) form.append('cooling_off_months', coolingOffMonths);
  // Deliberately NOT setting Content-Type here - the browser/axios auto-generates
  // "multipart/form-data; boundary=..." for a FormData body. Overriding it manually
  // (without a boundary) breaks server-side multipart parsing entirely.
  return axiosClient.post(`/batches/${batchId}/upload/`, form).then((r) => r.data);
};

// Returns { rows, summary: { total, valid, invalid } }. The summary comes from the server
// rather than being counted in the browser so the review screen and the finalize gate can
// never disagree about how many rows are valid.
export const getStagingCandidates = (batchId) =>
  axiosClient.get(`/batches/${batchId}/candidates/`).then((r) => r.data);

// Correct one row in place. Responds with the WHOLE table again, not just this row: fixing a
// mistyped address can turn another row into a duplicate of it (or clear one), so every row's
// verdict and the summary counts have to be refreshed together.
export const updateStagingCandidate = (batchId, candidateId, payload) =>
  axiosClient
    .patch(`/batches/${batchId}/candidates/${candidateId}/`, payload)
    .then((r) => r.data);

export const downloadValidationReport = async (batchId) => {
  const response = await axiosClient.get(
    `/batches/${batchId}/candidates/validation-report/`, { responseType: 'blob' },
  );
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement('a');
  link.href = url;
  link.download = `batch-${batchId}-validation-errors.xlsx`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};

export const deleteCandidates = (batchId, candidateIds) =>
  axiosClient
    .post(`/batches/${batchId}/candidates/delete/`, { candidate_ids: candidateIds })
    .then((r) => r.data);

// candidateIds is the reviewer's checkbox selection - finalizing creates the batch and
// emails the invite to exactly those candidates, and nobody else.
export const finalizeBatch = (batchId, candidateIds) =>
  axiosClient
    .post(`/batches/${batchId}/finalize/`, { candidate_ids: candidateIds })
    .then((r) => r.data);

// Always an explicit selection - the backend rejects a send with no candidate_ids so a
// blanket "invite everyone still pending" can't happen by accident.
export const sendInvites = (batchId, candidateIds) =>
  axiosClient
    .post(`/batches/${batchId}/send-invites/`, { candidate_ids: candidateIds })
    .then((r) => r.data);
