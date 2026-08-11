import axiosClient from './axiosClient';

// Returns the paginated envelope {count, next, previous, results} - callers that just want
// every batch for a dropdown (not a browsable list) should pass a page_size big enough to
// cover realistic batch counts in one page (e.g. { pageSize: 200 }).
export const listBatches = (search = '', { page, pageSize } = {}) => {
  const params = {};
  if (search) params.search = search;
  if (page) params.page = page;
  if (pageSize) params.page_size = pageSize;
  return axiosClient.get('/batches/', { params }).then((r) => r.data);
};

export const getBatch = (id) => axiosClient.get(`/batches/${id}/`).then((r) => r.data);

export const createBatch = (payload) => axiosClient.post('/batches/', payload).then((r) => r.data);

export const updateBatch = (id, payload) =>
  axiosClient.patch(`/batches/${id}/`, payload).then((r) => r.data);

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

export const getStagingCandidates = (batchId) =>
  axiosClient.get(`/batches/${batchId}/candidates/`).then((r) => r.data);

export const deleteCandidates = (batchId, candidateIds) =>
  axiosClient
    .post(`/batches/${batchId}/candidates/delete/`, { candidate_ids: candidateIds })
    .then((r) => r.data);

export const clearDuplicate = (batchId, candidateId) =>
  axiosClient.post(`/batches/${batchId}/candidates/${candidateId}/clear-duplicate/`).then((r) => r.data);

export const finalizeBatch = (batchId) =>
  axiosClient.post(`/batches/${batchId}/finalize/`).then((r) => r.data);

export const sendInvites = (batchId) =>
  axiosClient.post(`/batches/${batchId}/send-invites/`).then((r) => r.data);
