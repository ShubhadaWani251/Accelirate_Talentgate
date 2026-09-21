import axiosClient from './axiosClient';

export const getSections = () => axiosClient.get('/questions/sections/').then((r) => r.data);

// Adds an exam section. Only a name is needed - the server derives the stable section_key from
// it, because that key is what every score row, filter param and export column is keyed on and
// is not something an Admin should be choosing. A new section reaches new batches, the candidate
// tables, the Excel export and Configure Default Batch immediately; it never touches a batch
// that already exists, since each one snapshots its sections at creation.
export const createSection = (payload) =>
  axiosClient.post('/questions/sections/', payload).then((r) => r.data);

// Only succeeds while nothing depends on the section. The server refuses with a 400 carrying
// the question/batch counts once it holds questions or a batch has run it - deleting then would
// either take the question bank's content with it or erase what a cohort was assessed on.
export const deleteSection = (id) =>
  axiosClient.delete(`/questions/sections/${id}/`).then((r) => r.data);

// Retire (false) or restore (true). A retired section stays out of new batches while every
// existing batch and score under it is untouched - the answer for one that can't be deleted.
export const setSectionActive = (id, isActive) =>
  axiosClient.patch(`/questions/sections/${id}/`, { is_active: isActive }).then((r) => r.data);

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

// Two-phase upload. Validate returns per-row results without writing anything; import runs
// the same server-side validation again and writes only the rows that pass. Section comes from
// each row's own Section column, so one sheet may span several sections.
const questionUploadForm = (file, validateOnly) => {
  const form = new FormData();
  form.append('file', file);
  if (validateOnly) form.append('validate_only', 'true');
  return form;
};

export const validateQuestionsExcel = (file) =>
  axiosClient.post('/questions/upload/', questionUploadForm(file, true)).then((r) => r.data);

export const importQuestionsExcel = (file) =>
  axiosClient.post('/questions/upload/', questionUploadForm(file, false)).then((r) => r.data);

// Re-validate rows edited on the validation screen (or import them once they pass). The server
// runs the same validation either way, so an edited-to-invalid row still can't be written.
export const validateQuestionRows = (rows) =>
  axiosClient.post('/questions/validate-rows/', { rows, validate_only: true }).then((r) => r.data);

export const importQuestionRows = (rows) =>
  axiosClient.post('/questions/validate-rows/', { rows, validate_only: false }).then((r) => r.data);
