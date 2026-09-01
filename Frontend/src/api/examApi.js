import examAxiosClient from './examAxiosClient';

export const getTokenLanding = (token) =>
  examAxiosClient.get(`/exam/token/${token}/`).then((r) => r.data);

export const verifyEmail = (token, email) =>
  examAxiosClient.post(`/exam/token/${token}/verify-email/`, { email }).then((r) => r.data);

export const submitIdentity = (token, idPhotoBlob, facePhotoBlob) => {
  const form = new FormData();
  form.append('id_photo', idPhotoBlob, 'id_photo.jpg');
  form.append('face_photo', facePhotoBlob, 'face_photo.jpg');
  return examAxiosClient.post(`/exam/token/${token}/identity/`, form).then((r) => r.data);
};

// Starts the server-side clock. Called only once the candidate is actually in the exam window -
// never from the identity/instructions screens.
export const beginExam = () => examAxiosClient.post('/exam/begin/').then((r) => r.data);

export const getSession = () => examAxiosClient.get('/exam/session/').then((r) => r.data);

// markedForReview omitted (undefined) leaves the flag as-is server-side - selectedOption has no
// such "don't touch" option, so a review-only toggle (see setMarkedForReview below) must always
// resend the candidate's current selection, never omit it.
export const saveAnswer = (questionId, selectedOption, timeSpentSeconds, markedForReview) =>
  examAxiosClient
    .patch(`/exam/answers/${questionId}/`, {
      selected_option: selectedOption || '',
      ...(timeSpentSeconds != null ? { time_spent_seconds: timeSpentSeconds } : {}),
      ...(markedForReview != null ? { marked_for_review: markedForReview } : {}),
    })
    .then((r) => r.data);

// Toggling the flag without touching the answer - selectedOption is passed through unchanged
// since the backend always applies it (see saveAnswer's comment above).
export const setMarkedForReview = (questionId, selectedOption, markedForReview) =>
  saveAnswer(questionId, selectedOption, undefined, markedForReview);

export const uploadRecordingChunk = (chunkBlob) =>
  examAxiosClient.post('/exam/recording/chunk/', chunkBlob, {
    headers: { 'Content-Type': 'application/octet-stream' },
  });

// Reports a proctoring trigger. The SERVER decides whether it's a warning or a termination -
// leaving the exam window earns one warning first, a devtools/screenshot key or a lost camera
// does not. Resolves to { action: 'warned' | 'terminated' | 'already_closed', detail, reason,
// warnings_used, warnings_allowed }. Never assume termination from the fact that this was called.
export const reportViolation = (reason) =>
  examAxiosClient.post('/exam/violation/', reason ? { reason } : {}).then((r) => r.data);

export const submitExam = () => examAxiosClient.post('/exam/submit/').then((r) => r.data);
