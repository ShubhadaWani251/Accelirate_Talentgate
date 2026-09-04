// Detects whether the page is already running inside Safe Exam Browser, so the choice screen
// (ExamSebChoice.jsx) can skip straight past its own question for a candidate who's already
// there - asking "do you want to launch SEB?" while already inside it is a dead end, not a
// safeguard.
//
// Deliberately low-stakes: this is the one place in the app that sniffs the browser rather than
// feature-detecting a capability (compare FULLSCREEN_SUPPORTED in ../proctoring/fullscreen.js),
// and User-Agent strings are trivially spoofable. That's acceptable here specifically because
// nothing security-relevant reads this - it only ever decides whether to show one screen's
// question. The real verification (was this candidate's request genuinely from SEB) happens
// server-side against a signed header (see Backend/api/services/seb.py), never against this.
//
// TODO confirm against SEB's current developer documentation: the exact shape of
// window.SafeExamBrowser (if the currently-deployed SEB versions still expose it) and the exact
// User-Agent substring for current releases. "SEB" is SEB's own long-standing convention, but
// this hasn't been verified against a real, current SEB client.
export function isRunningInSeb() {
  if (typeof window !== 'undefined' && window.SafeExamBrowser) return true;
  if (typeof navigator === 'undefined') return false;
  return /SEB/.test(navigator.userAgent);
}
