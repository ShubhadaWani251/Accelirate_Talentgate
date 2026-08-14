import axiosClient from './axiosClient';

export const getSections = () => axiosClient.get('/questions/sections/').then((r) => r.data);

// Returns the paginated envelope {count, next, previous, results}.
export const listQuestions = (filters = {}) => {
  const params = {};
  Object.entries(filters).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined) params[key] = value;
  });
  return axiosClient.get('/questions/', { params }).then((r) => r.data);
};

export const createQuestion = (payload) => axiosClient.post('/questions/', payload).then((r) => r.data);

export const updateQuestion = (id, payload) =>
  axiosClient.patch(`/questions/${id}/`, payload).then((r) => r.data);

// Same authenticated-blob-download pattern as batchApi.downloadTemplate.
export const downloadQuestionTemplate = async () => {
  const response = await axiosClient.get('/questions/template/', { responseType: 'blob' });
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement('a');
  link.href = url;
  link.download = 'question_upload_template.xlsx';
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};

// `sectionKey` files every row into that section, ignoring the sheet's own Section column -
// the upload is always launched from inside a section.
export const uploadQuestionsExcel = (file, sectionKey) => {
  const form = new FormData();
  form.append('file', file);
  if (sectionKey) form.append('section', sectionKey);
  return axiosClient.post('/questions/upload/', form).then((r) => r.data);
};
