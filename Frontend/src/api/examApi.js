import examAxiosClient from './examAxiosClient';

export const getTokenLanding = (token) =>
  examAxiosClient.get(`/exam/token/${token}/`).then((r) => r.data);

export const verifyEmail = (token, email) =>
  examAxiosClient.post(`/exam/token/${token}/verify-email/`, { email }).then((r) => r.data);

// First identity-capture step - the Aadhaar Card photo. Separate from submitIdentity below so a
// real verification verdict (and a limited retry) can happen before face-photo capture is even
// reachable - see ExamIdentityAadhaarCaptureView. Callable more than once (retakes); the server
// enforces the retry cap, not this function.
export const captureAadhaarPhoto = (token, idPhotoBlob) => {
  const form = new FormData();
  // An uploaded file (allowUpload on PhotoCapture) has its own real name/extension; a live
  // webcam capture is a bare canvas Blob with none, so it falls back to the original name.
  form.append('id_photo', idPhotoBlob, idPhotoBlob.name || 'id_photo.jpg');
  return examAxiosClient.post(`/exam/token/${token}/identity/aadhaar/`, form).then((r) => r.data);
};

// Second identity-capture step - the face photo, only reachable once the Aadhaar step above has
// resolved (matched, or retries exhausted and flagged - never blocked).
// extraFaceSeen reports that more than one person was on camera at some point during identity
// verification. It never blocks anything - capture is already disabled while a second face is
// visible, so this always arrives after they have stepped away - it exists so the TA can see
// afterwards that it happened at all, which previously nothing recorded.
export const submitIdentity = (token, facePhotoBlob, extraFaceSeen = false) => {
  const form = new FormData();
  form.append('face_photo', facePhotoBlob, 'face_photo.jpg');
  if (extraFaceSeen) form.append('extra_face_seen', 'true');
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

// Recording chunks go STRAIGHT TO AZURE BLOB STORAGE where that is possible, and through the
// server only when it is not.
//
// The server path holds a gunicorn thread for the candidate's upload and then the server's own,
// and staging has four threads across the whole deployment. On 2026-10-05 chunk uploads ran to a
// median of 1.6s and a worst case of 36s, in-flight requests hit that ceiling of 4, and ten
// requests were failed by the platform without reaching Django at all. Video was eating the
// slots the exam needed.
//
// Direct upload needs CORS on the storage account, which is an Azure-side change this code
// cannot make. So it is written to be deployed BEFORE that exists: every failure falls back to
// the server path, which is unchanged and still correct. Nothing here is a flag day - the
// improvement simply starts applying the moment CORS is configured.
let uploadTarget = null;        // { url, expiresAt } for the current short-lived SAS
let uploadTargetPromise = null; // in-flight request for one, so N chunks don't fetch N URLs
let directFailures = 0;

// After this many consecutive failures, stop trying direct upload for the rest of the session.
// Without it, an account with no CORS rule costs every single chunk a doomed round-trip before
// the fallback even starts - slower than never having tried.
const DIRECT_UPLOAD_GIVE_UP_AFTER = 2;

function directUploadUnavailable() {
  return directFailures >= DIRECT_UPLOAD_GIVE_UP_AFTER;
}

async function currentUploadTarget() {
  if (directUploadUnavailable()) return null;
  if (uploadTarget && Date.now() < uploadTarget.expiresAt) return uploadTarget.url;
  if (!uploadTargetPromise) {
    uploadTargetPromise = examAxiosClient
      .get('/exam/recording/upload-url/')
      .then((r) => {
        // ttl_seconds is deliberately shorter than the token really lasts, so a refresh that is
        // itself slow still lands before the old one dies.
        uploadTarget = r.data?.url
          ? { url: r.data.url, expiresAt: Date.now() + (r.data.ttl_seconds || 60) * 1000 }
          : null;
        return uploadTarget?.url ?? null;
      })
      .catch(() => null)
      .finally(() => { uploadTargetPromise = null; });
  }
  return uploadTargetPromise;
}

export const uploadRecordingChunk = async (chunkBlob) => {
  const target = await currentUploadTarget();
  if (target) {
    try {
      // Azure's Append Block operation. The SAS carries add permission only, so this can extend
      // this one recording and do nothing else - not read it back, not overwrite it, not touch
      // another attempt.
      const res = await fetch(`${target}&comp=appendblock`, {
        method: 'PUT',
        body: chunkBlob,
      });
      if (res.ok) { directFailures = 0; return res; }
      // A 403 is usually the token having expired early; drop it so the next chunk re-mints one
      // rather than replaying a dead token.
      if (res.status === 403) uploadTarget = null;
      directFailures += 1;
    } catch {
      // Thrown rather than returned means the browser blocked it outright - CORS not configured
      // on the storage account is exactly this shape.
      directFailures += 1;
    }
  }
  return examAxiosClient.post('/exam/recording/chunk/', chunkBlob, {
    headers: { 'Content-Type': 'application/octet-stream' },
  });
};

// Reports a proctoring trigger. The SERVER decides whether it's a warning or a termination -
// leaving the exam window draws on a shared budget of three warnings first, a devtools/screenshot
// key does not. Resolves to { action: 'warned' | 'terminated' | 'already_closed', detail, reason,
// warnings_used, warnings_allowed }. Never assume termination from the fact that this was called.
// `extra` carries reason-specific evidence (currently only forbidden_object_detected sends
// detected_object/confidence) - spread alongside reason rather than nested, matching how
// TerminateSerializer reads them as top-level fields.
export const reportViolation = (reason, extra) =>
  examAxiosClient.post('/exam/violation/', { ...(reason ? { reason } : {}), ...(extra || {}) })
    .then((r) => r.data);

export const submitExam = () => examAxiosClient.post('/exam/submit/').then((r) => r.data);
