import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import * as examApi from '../../api/examApi';
import { useExamSession } from '../../features/exam/examSessionContext';
import useExamTimer from '../../features/exam/timer/useExamTimer';
import useTabSwitchGuard from '../../features/exam/proctoring/useTabSwitchGuard';
import useFullscreenGuard from '../../features/exam/proctoring/useFullscreenGuard';
import useExamLockdown from '../../features/exam/proctoring/useExamLockdown';
import useDisplayGuard from '../../features/exam/proctoring/useDisplayGuard';
import useCameraGuard from '../../features/exam/proctoring/useCameraGuard';
import useSessionRecorder from '../../features/exam/webcam/useSessionRecorder';
import useCameraStream from '../../features/exam/webcam/useCameraStream';
import { checkCameraNotBlocked } from '../../features/exam/webcam/frameCheck';
import {
  FULLSCREEN_SUPPORTED, enterFullscreen, exitFullscreen, isFullscreen,
} from '../../features/exam/proctoring/fullscreen';
import { ButtonSpinner } from '../../components/loading/Spinner';
import {
  REASON_SETTLE_MS, moreSpecificReason,
} from '../../features/exam/proctoring/violationReasons';
import BrandHeader from '../../components/layout/BrandHeader';
import BrandFooter from '../../components/layout/BrandFooter';
import ExamResult from './ExamResult';
import ExamTerminated from './ExamTerminated';

const OPTIONS = ['A', 'B', 'C', 'D'];
const OPTION_LABEL_KEY = { A: 'option_a', B: 'option_b', C: 'option_c', D: 'option_d' };

function flattenAnswers(sections) {
  const answers = {};
  sections.forEach((section) => {
    section.questions.forEach((q) => {
      answers[q.question_id] = q.selected_option || '';
    });
  });
  return answers;
}

function flattenMarks(sections) {
  const marks = {};
  sections.forEach((section) => {
    section.questions.forEach((q) => {
      marks[q.question_id] = Boolean(q.marked_for_review);
    });
  });
  return marks;
}

export default function ExamAttemptPage() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { sessionState, setSessionState, restoreAttemptToken, mediaStreamRef } = useExamSession();

  const [view, setView] = useState('loading'); // loading | exam | result | terminated
  const [answers, setAnswers] = useState({});
  const [markedForReview, setMarkedForReview] = useState({});
  // Which section page is showing. Sections stay freely revisitable - this is plain navigation
  // state, not a progress lock, and not tied to any per-section timer (there isn't one - only
  // the overall exam countdown below governs timing).
  const [activeSectionIndex, setActiveSectionIndex] = useState(0);
  const [showConfirm, setShowConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [terminationMessage, setTerminationMessage] = useState('');
  // The one warning a candidate gets for leaving the exam window: { detail, used, allowed }, or
  // null. Purely for display - the authoritative count lives on the server, so this is not what
  // stops a second warning being issued.
  const [warning, setWarning] = useState(null);
  // Re-arm counters for the guards' once-only latches. Two of them, because the window guards
  // and the full-screen guard have to come back at different moments - see onViolation and
  // acknowledgeWarning.
  const [windowGuardGen, setWindowGuardGen] = useState(0);
  const [fullscreenGuardGen, setFullscreenGuardGen] = useState(0);
  // Gates the actual question content behind a full-screen entry click - requestFullscreen()
  // needs a real user gesture, so it can't fire automatically on page load. Already true if the
  // candidate is arriving from the earlier ExamFullscreenGate screen (the normal path) - this
  // gate is really only reached on a refresh/resume, since a page reload always exits
  // full-screen. A browser with no Fullscreen API support (rare) skips the gate entirely.
  const [fullscreenReady, setFullscreenReady] = useState(
    !FULLSCREEN_SUPPORTED || isFullscreen()
  );
  // A page reload always drops both full-screen AND the getUserMedia stream (a MediaStream
  // can't survive a reload) - fullscreenReady above already re-gates on the former, this
  // re-gates on the latter. Without it, a candidate who reloaded mid-exam kept answering with
  // no camera stream at all: useCameraGuard/useSessionRecorder silently do nothing when there's
  // no stream to check, so proctoring went dark for the rest of the attempt with no error and
  // nothing for the candidate to even notice. Starts true on the normal first-time path (camera
  // was just granted on ExamCameraPermission and handed off via mediaStreamRef), so this only
  // ever gates a resume.
  const [cameraAcquired, setCameraAcquired] = useState(Boolean(mediaStreamRef.current));
  const [cameraRequesting, setCameraRequesting] = useState(false);
  const [cameraBlocked, setCameraBlocked] = useState(false);
  const { requestStream, error: cameraError } = useCameraStream();
  // Seconds left to enter full-screen before the attempt is ended for it - ticks only while
  // this specific gate (camera already reacquired, full-screen not yet) is showing.
  const [fullscreenSecondsLeft, setFullscreenSecondsLeft] = useState(30);
  // The clock is started by the server on POST /exam/begin/, which only happens once the
  // candidate is genuinely in the exam window (full-screen satisfied). Questions and the
  // countdown are withheld until that call returns, so the timer can never be shown - or run -
  // before the server considers the exam started.
  const [begun, setBegun] = useState(false);
  // Set only for the one error worth telling the candidate about (the window hasn't opened
  // yet) - a plain network blip stays silent and just retries, per the existing catch below.
  const [beginError, setBeginError] = useState(null);
  const beginRequestedRef = useRef(false);

  useEffect(() => {
    if (sessionState) {
      setAnswers(flattenAnswers(sessionState.sections));
      setMarkedForReview(flattenMarks(sessionState.sections));
      setView('exam');
      return;
    }
    // Refresh/crash recovery: the attempt JWT survives in sessionStorage even though the
    // in-memory sessionState context does not.
    const restored = restoreAttemptToken(token);
    if (!restored) {
      navigate(`/t/${token}`, { replace: true });
      return;
    }
    examApi
      .getSession()
      .then((data) => {
        setSessionState(data);
        setAnswers(flattenAnswers(data.sections));
        setMarkedForReview(flattenMarks(data.sections));
        setView('exam');
      })
      .catch(() => navigate(`/t/${token}`, { replace: true }));
  }, [sessionState, restoreAttemptToken, setSessionState, navigate, token]);

  const finishExam = useCallback(async () => {
    setSubmitting(true);
    try {
      const data = await examApi.submitExam();
      setResult(data);
      setView('result');
    } catch {
      // The attempt is server-finalized regardless (time-expiry auto-finalizes on the next
      // authenticated call) - show the terminal state either way rather than leaving the
      // candidate stuck on a dead countdown.
      setView('result');
      setResult({ result: 'pending', total_correct: 0, total_answered: 0, sections: [] });
    } finally {
      setSubmitting(false);
    }
  }, []);

  // Single latch shared by ALL guards. Each guard hook has its own internal one, but that isn't
  // enough on its own: one real action commonly trips two different guards (F12 fires the key
  // handler AND blurs the window), which previously sent two terminate calls - the second hitting
  // a 401 "already closed" and overwriting the correct message with a false camera/mic error.
  const violationRef = useRef({ fired: false, reason: null, timer: null });

  const onViolation = useCallback((reason) => {
    const state = violationRef.current;
    if (state.fired) return;

    // Keep the most specific reason seen during the settle window rather than whichever arrived
    // first - see violationReasons.js for why the vaguest cause tends to arrive first.
    state.reason = moreSpecificReason(state.reason, reason);
    if (state.timer) return;

    state.timer = setTimeout(() => {
      state.fired = true;
      examApi
        .reportViolation(state.reason)
        .then((data) => {
          // The SERVER decides warn-vs-terminate; this only renders the outcome. Leaving the
          // exam window earns one warning, counted in the database so a reload can't earn
          // another - see exam_session.record_violation.
          if (data.action === 'warned') {
            setWarning({ detail: data.detail, used: data.warnings_used,
                         allowed: data.warnings_allowed });
            // Re-arm the window guards NOW, not on acknowledgement. Otherwise a candidate
            // could take their warning and then read notes in another window for as long as
            // they left the modal open, with every further trigger swallowed by the latches.
            // The full-screen guard is deliberately left latched until acknowledgeWarning has
            // actually restored full-screen - re-arming it here would fire it immediately on
            // the very state the warning was just given for.
            state.fired = false;
            state.reason = null;
            state.timer = null;
            setWindowGuardGen((g) => g + 1);
            return;
          }
          setTerminationMessage(data.detail);
          setView('terminated');
        })
        .catch(() => {
          // Only reached when the call itself failed, so the real outcome is unknown. Ending
          // the attempt is the safe default - treating an unreachable server as "warning
          // granted" would let a dropped connection buy unlimited tab switches. Deliberately
          // cause-agnostic: it must NOT claim a specific cause (it previously asserted
          // camera/mic loss, which was simply wrong for e.g. a devtools attempt).
          setTerminationMessage(
            'Your assessment was ended and could not be reported to the server. '
            + 'Please contact the Staffing team.'
          );
          setView('terminated');
        });
    }, REASON_SETTLE_MS);
  }, []);

  // Acknowledging the warning puts the candidate back in full-screen and re-arms the
  // full-screen guard. A tab switch usually drops full-screen on its way out (Chrome releases
  // it when the tab is backgrounded), so without re-entering here the candidate would sit
  // outside full-screen and be terminated for it moments later. requestFullscreen needs a real
  // user gesture - this button click is that gesture, which is why the warning is a dismissible
  // modal rather than a toast that fades on its own.
  const acknowledgeWarning = useCallback(async () => {
    const state = violationRef.current;
    // Suppressed across the transition only: entering full-screen can itself produce a
    // transient focus event, and the window guards are live by this point (re-armed when the
    // warning arrived), so without this the acknowledgement click could terminate the
    // candidate for the act of complying.
    state.fired = true;
    if (state.timer) {
      clearTimeout(state.timer);
      state.timer = null;
    }
    setWarning(null);
    if (FULLSCREEN_SUPPORTED && !isFullscreen()) await enterFullscreen();
    state.fired = false;
    state.reason = null;
    // Re-armed last, once full-screen is actually back.
    setFullscreenGuardGen((g) => g + 1);
  }, []);

  const examActive = view === 'exam' && fullscreenReady && begun;

  // Start the server-side clock exactly once, the moment the candidate is really in the exam
  // window (loaded + full-screen satisfied). Kept out of the identity/instructions screens
  // entirely so no time is charged for reading them.
  useEffect(() => {
    if (view !== 'exam' || !fullscreenReady || beginRequestedRef.current) return;
    beginRequestedRef.current = true;
    examApi
      .beginExam()
      .then((data) => {
        // The response carries the authoritative remaining_seconds; the countdown is seeded from
        // it rather than from anything computed before this point.
        setSessionState(data);
        setAnswers(flattenAnswers(data.sections));
        setBegun(true);
      })
      .catch((err) => {
        // The one error worth telling the candidate about rather than silently retrying: the
        // batch's window hasn't opened yet. Reachable here only if the earlier gates (landing,
        // email-verify, identity-capture) were somehow bypassed, since none of them let a
        // candidate reach this screen before the window opens - kept as the authoritative
        // last-line check regardless. Every other failure (already-closed/expired attempts 401
        // here; auth-layer handling covers those, or a transient network blip) keeps retrying
        // rather than latching into a dead end.
        if (err.response?.data?.opens_at) {
          setBeginError(err.response.data.detail);
          return;
        }
        beginRequestedRef.current = false;
      });
  }, [view, fullscreenReady, setSessionState]);

  // Only counts down once the server has actually started the exam - the `begun` gate also stops
  // it from ticking 0 -> onExpire and auto-submitting a blank paper before the exam starts.
  const timer = useExamTimer(sessionState?.remaining_seconds ?? 0, finishExam, begun);
  // Gated on fullscreenReady, not just view === 'exam': without this, a candidate sitting on
  // the camera-recheck or "Enter Full-Screen" gate (reached on a resume, see below) could be
  // terminated for a tab switch/window blur before the exam has functionally resumed at all -
  // nothing should end the attempt on those gates except the 30-second fullscreen timer itself.
  useTabSwitchGuard(view === 'exam' && fullscreenReady, onViolation, windowGuardGen);
  useFullscreenGuard(examActive, onViolation, fullscreenGuardGen);
  useExamLockdown(examActive, onViolation, windowGuardGen);
  useSessionRecorder(mediaStreamRef.current, examActive);

  // A second display appearing mid-exam is treated the same way as leaving the window: one
  // warning, then the attempt ends. It rides on the existing violation pipeline rather than
  // having its own path, so the warning count is shared - a candidate cannot spend one warning
  // on a tab switch and another on a monitor.
  //
  // Reported as window_blur because that is the closest existing reason code, and the candidate
  // is shown the extraDisplay banner below explaining the real cause. A dedicated reason code
  // would need a matching TERMINATION_MESSAGES entry on the server to avoid a KeyError.
  const { extended: extraDisplay } = useDisplayGuard(examActive);
  useEffect(() => {
    if (examActive && extraDisplay) onViolation('window_blur');
  }, [examActive, extraDisplay, onViolation]);

  // The camera going off mid-exam - switched off, covered by a privacy shutter, or taken by
  // another application. Warnable (see exam_session.WARNABLE_REASONS): the candidate gets one
  // chance to turn it back on, and the banner below tells them to. Video is handled here rather
  // than by the system_issue listener beneath because the two need different outcomes, and
  // because the signals differ - see useCameraGuard for why watching only `ended` missed this
  // entirely.
  const { cameraOff } = useCameraGuard(mediaStreamRef, examActive, onViolation);

  // "System issue" - the MICROPHONE feed the recorder depends on disappearing mid-exam. Not the
  // candidate's fault, so finalize_attempt/is_violation_reason on the backend keeps this out of
  // their violation record even though the attempt still has to end: unlike the camera, there is
  // nothing a warning could ask them to do about it.
  //
  // Scoped to audio tracks only. It used to cover every track, which meant a camera switched off
  // hard enough to end its track was reported as a technical fault and terminated silently
  // instead of earning the warning it should.
  useEffect(() => {
    if (!examActive) return undefined;
    const stream = mediaStreamRef.current;
    if (!stream) return undefined;
    const tracks = stream.getAudioTracks();
    function handleEnded() {
      onViolation('system_issue');
    }
    tracks.forEach((t) => t.addEventListener('ended', handleEnded));
    return () => tracks.forEach((t) => t.removeEventListener('ended', handleEnded));
  }, [examActive, mediaStreamRef, onViolation]);

  // Release full-screen (and the camera/mic) once the attempt is over - the candidate is locked
  // into full-screen only while the exam is live. Safe to exit here without tripping
  // useFullscreenGuard: `view` has already changed, so React ran that effect's cleanup (removing
  // its fullscreenchange listener) before this effect fires.
  useEffect(() => {
    if (view !== 'result' && view !== 'terminated') return;
    exitFullscreen();
    const stream = mediaStreamRef.current;
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      mediaStreamRef.current = null;
    }
  }, [view, mediaStreamRef]);

  async function onEnterFullscreen() {
    // Bounded (see fullscreen.js) so a request that never settles can't strand the candidate on
    // this gate. Proceeding even if full-screen didn't take is deliberate - this gate is only
    // reached on a refresh/resume, where the clock is already running, so blocking here would
    // silently burn the candidate's remaining time.
    await enterFullscreen();
    setFullscreenReady(true);
  }

  async function onAllowCamera() {
    setCameraRequesting(true);
    setCameraBlocked(false);
    try {
      const { stream, noVideo } = await requestStream();
      if (!noVideo) {
        const { blocked } = await checkCameraNotBlocked(stream);
        if (blocked) {
          stream.getTracks().forEach((t) => t.stop());
          setCameraBlocked(true);
          return;
        }
      }
      mediaStreamRef.current = stream;
      setCameraAcquired(true);
    } catch {
      // cameraError below renders the failure state.
    } finally {
      setCameraRequesting(false);
    }
  }

  // 30-second grace period to re-enter full-screen, counted only once the candidate has a
  // camera stream again (so the two gates never race) and only while genuinely on this specific
  // step - a candidate who has already begun the exam and reloaded, camera reacquired, sitting
  // on the "Enter Full-Screen" button. Not entering it in time ends the attempt: zero-tolerance,
  // same as a deliberate devtools/screenshot attempt, since there is no legitimate reason to sit
  // on this screen at length once everything else is in place. Nothing terminates before this -
  // useTabSwitchGuard below is deliberately gated on fullscreenReady too, so it cannot fire
  // while still on this gate.
  useEffect(() => {
    if (view !== 'exam' || !cameraAcquired || fullscreenReady) return undefined;
    setFullscreenSecondsLeft(30);
    const interval = setInterval(() => {
      setFullscreenSecondsLeft((s) => Math.max(0, s - 1));
    }, 1000);
    const timeout = setTimeout(() => {
      examApi
        .reportViolation('fullscreen_not_entered')
        .then((data) => {
          setTerminationMessage(data.detail);
          setView('terminated');
        })
        .catch(() => {
          setTerminationMessage(
            'Your assessment was ended and could not be reported to the server. '
            + 'Please contact the Staffing team.'
          );
          setView('terminated');
        });
    }, 30000);
    return () => {
      clearInterval(interval);
      clearTimeout(timeout);
    };
  }, [view, cameraAcquired, fullscreenReady]);

  function onSelectOption(questionId, option) {
    setAnswers((prev) => ({ ...prev, [questionId]: option }));
    examApi.saveAnswer(questionId, option).catch(() => {});
  }

  function onToggleReview(questionId) {
    const next = !markedForReview[questionId];
    setMarkedForReview((prev) => ({ ...prev, [questionId]: next }));
    // Resends the current selection alongside the flag - selected_option has no "leave as-is"
    // sentinel server-side, so omitting it here would clear whatever the candidate had picked.
    examApi.setMarkedForReview(questionId, answers[questionId], next).catch(() => {});
  }

  const totalCount = Object.keys(answers).length;
  const unansweredCount = useMemo(
    () => Object.values(answers).filter((v) => !v).length,
    [answers]
  );
  const answeredCount = totalCount - unansweredCount;
  const markedCount = useMemo(
    () => Object.values(markedForReview).filter(Boolean).length,
    [markedForReview]
  );

  async function onConfirmSubmit() {
    setShowConfirm(false);
    await finishExam();
  }

  if (view === 'loading') return null;
  if (view === 'terminated') return <ExamTerminated message={terminationMessage} />;
  if (view === 'result') return <ExamResult result={result} />;

  // Only ever reached on a resume (see cameraAcquired's own comment) - the normal first-time
  // path already has a stream handed off from ExamCameraPermission before it ever reaches here.
  if (!cameraAcquired) {
    return (
      <div className="app-shell">
        <BrandHeader roleCode="candidate" />
        <div className="auth-shell">
          <div className="auth-card" style={{ textAlign: 'center' }}>
            <h3>Camera &amp; Microphone Access Required</h3>
            <div className="auth-sub">
              Your camera and microphone need to be re-enabled to continue this assessment -
              continuous video and audio is mandatory for the whole exam, including after a
              reload.
            </div>

            {cameraBlocked && (
              <div className="alert error" style={{ textAlign: 'left' }}>
                <b>Your camera appears to be covered.</b>
                <div style={{ marginTop: 6 }}>
                  Access was granted, but no image is coming through. Please open your camera's
                  privacy shutter (or remove any cover/tape over the lens) and try again.
                </div>
              </div>
            )}

            {cameraError && (
              <div className="alert error" style={{ fontFamily: 'monospace', fontSize: 11.5 }}>
                {cameraError.name}: {cameraError.message}
              </div>
            )}

            <button className="btn primary block" type="button" disabled={cameraRequesting}
                    onClick={onAllowCamera}>
              {cameraRequesting ? 'Checking camera…'
                : cameraBlocked ? 'Check Camera Again' : 'Allow Camera & Microphone Access'}
            </button>
          </div>
        </div>
        <BrandFooter roleCode="candidate" />
      </div>
    );
  }

  if (!fullscreenReady) {
    return (
      <div className="app-shell">
        <BrandHeader roleCode="candidate" />
        <div className="auth-shell">
          <div className="auth-card" style={{ textAlign: 'center' }}>
            <h3>Enter Full-Screen to Begin</h3>
            <div className="auth-sub">
              The assessment runs in full-screen mode. Exiting full-screen, switching tabs or
              leaving this window gives you one warning; the second time, your attempt ends
              automatically. Every such event is logged — per the integrity rules shown earlier.
            </div>
            <div className="auth-sub" style={{ fontWeight: 600,
                         color: fullscreenSecondsLeft <= 10 ? 'var(--brand-red)' : undefined }}>
              Enter full-screen within {fullscreenSecondsLeft} second
              {fullscreenSecondsLeft === 1 ? '' : 's'}, or your assessment will be ended.
            </div>
            <button className="btn primary block" type="button" onClick={onEnterFullscreen}>
              Enter Full-Screen &amp; Begin
            </button>
          </div>
        </div>
        <BrandFooter roleCode="candidate" />
      </div>
    );
  }

  // Questions are withheld until the server has started the clock, so a candidate can never see
  // the paper while the timer is still at zero.
  if (!begun) {
    return (
      <div className="app-shell">
        <BrandHeader roleCode="candidate" />
        <div className="auth-shell">
          <div className="auth-card" style={{ textAlign: 'center' }}>
            {beginError ? (
              <>
                <h3>Assessment Not Open Yet</h3>
                <div className="auth-sub">{beginError}</div>
              </>
            ) : (
              <>
                <h3>Starting your assessment…</h3>
                <div className="auth-sub">Your timer begins now. Please don't close this window.</div>
              </>
            )}
          </div>
        </div>
        <BrandFooter roleCode="candidate" />
      </div>
    );
  }

  const lowTime = timer.remaining <= 300; // last 5 minutes
  const sections = sessionState.sections;
  const activeSection = sections[activeSectionIndex] || sections[0];

  return (
    <div className="app-shell">
      <BrandHeader roleCode="candidate" />
      <div style={{ flex: 1, padding: '20px 16px', maxWidth: 760, margin: '0 auto', width: '100%' }}>
        {extraDisplay && (
          <div className="alert error" style={{ marginBottom: 10 }}>
            <b>More than one display detected.</b> The assessment must be taken on a single
            screen. Disconnect the additional display immediately.
          </div>
        )}

        {/* Stays visible for as long as the camera is off, unlike the warning modal which the
            candidate dismisses. That matters: the guard reports once per switch-off and will not
            nag, so without a persistent banner someone who dismissed the warning before fixing
            the camera would have nothing left telling them the exam is still unproctored. */}
        {cameraOff && (
          <div className="alert error" style={{ marginBottom: 10 }}>
            <b>Your camera is not sending video.</b> Turn it back on now - check for a privacy
            shutter, your camera switch, or another app (Teams, Zoom) using the camera. If it
            goes off again your assessment will be ended.
          </div>
        )}

        {/* Fixed-feeling summary header: the overall countdown is what actually governs the
            exam (see remaining_seconds - a tampered client clock changes nothing), Answered/
            Remaining count every question across every section regardless of which page is
            showing. */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                     flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
          <h3 style={{ margin: 0 }}>Assessment</h3>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12.5, color: 'var(--muted)' }}>
              Answered <b>{answeredCount}</b> / {totalCount} &middot; Remaining <b>{unansweredCount}</b>
              {markedCount > 0 && <> &middot; Marked for Review <b>{markedCount}</b></>}
            </span>
            <div className={`timer-badge${lowTime ? ' low-time' : ''}`}>⏱ {timer.formatted} remaining</div>
          </div>
        </div>

        {/* One page per section, switched via the same stat-card picker as admin's Question
            Bank screen (QuestionBank.jsx) - each card doubles as both the section's identity
            and its own progress readout, and is clickable any time (sections stay freely
            revisitable - no lock on leaving one, no per-section timer). */}
        <div className="grid-4" style={{ marginBottom: 14 }}>
          {sections.map((section, idx) => {
            const attempted = section.questions.filter((q) => answers[q.question_id]).length;
            return (
              <button
                key={section.key}
                type="button"
                className={`stat-card qb-stat-card ${idx === activeSectionIndex ? 'active' : ''}`}
                onClick={() => setActiveSectionIndex(idx)}
                style={{ textAlign: 'center', cursor: 'pointer', border: 'none', width: '100%' }}
              >
                <div className="stat-lbl" style={{ fontWeight: 600 }}>{section.label}</div>
                <div className="stat-num">{attempted} / {section.questions.length}</div>
                <div className="stat-lbl">Attempted</div>
              </button>
            );
          })}
        </div>

        <div className="section-marker">
          {activeSection.label} ({activeSection.questions.length} question
          {activeSection.questions.length === 1 ? '' : 's'})
        </div>
        {activeSection.questions.map((q, idx) => (
          <div className="q-card" key={q.question_id}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div className="q-num">Question {idx + 1}</div>
              <button
                type="button"
                className={`btn small${markedForReview[q.question_id] ? ' primary' : ''}`}
                onClick={() => onToggleReview(q.question_id)}
              >
                {markedForReview[q.question_id] ? '★ Marked for Review' : '☆ Mark for Review'}
              </button>
            </div>
            <div className="q-text">{q.question_text}</div>
            {OPTIONS.filter((opt) => q[OPTION_LABEL_KEY[opt]]).map((opt) => (
              <label className="option-row" key={opt}>
                <input
                  type="radio"
                  name={`q-${q.question_id}`}
                  checked={answers[q.question_id] === opt}
                  onChange={() => onSelectOption(q.question_id, opt)}
                />
                {q[OPTION_LABEL_KEY[opt]]}
              </label>
            ))}
          </div>
        ))}

        <div className="btn-row" style={{ margin: '18px 0' }}>
          <button className="btn danger" type="button" onClick={() => setShowConfirm(true)}>
            Submit Exam
          </button>
        </div>
      </div>
      <BrandFooter roleCode="candidate" />

      {/* The single warning for leaving the exam window. Deliberately a blocking modal with one
          button, not a toast: dismissing it is the user gesture that lets requestFullscreen()
          put the candidate back in full-screen (see acknowledgeWarning), and a warning this
          consequential shouldn't be dismissible by being ignored. Rendered above the submit
          confirmation so the two can't be competing for attention. */}
      {warning && (
        <div className="modal-overlay">
          <div className="modal-box">
            <h4 style={{ color: 'var(--brand-red)' }}>⚠ Warning — Assessment Integrity</h4>
            <p>{warning.detail}</p>
            <p style={{ fontSize: 12.5, color: 'var(--muted)' }}>
              Warning {warning.used} of {warning.allowed}. This has been recorded and is visible
              to the Staffing team. Your timer has continued to run.
            </p>
            <div className="btn-row">
              <button className="btn primary block" type="button" onClick={acknowledgeWarning}>
                I understand — return to the assessment
              </button>
            </div>
          </div>
        </div>
      )}

      {showConfirm && !warning && (
        <div className="modal-overlay">
          <div className="modal-box">
            <h4>Submit Assessment?</h4>
            <p>
              {unansweredCount > 0
                ? `${unansweredCount} of ${totalCount} questions are still unanswered. `
                : ''}
              {markedCount > 0 ? `${markedCount} question${markedCount === 1 ? ' is' : 's are'} `
                + 'still marked for review. ' : ''}
              Are you sure you want to submit the exam now? This cannot be undone and you will
              not be able to resume.
            </p>
            <div className="btn-row">
              <button className="btn" type="button" onClick={() => setShowConfirm(false)}>
                Cancel, Go Back
              </button>
              <button className="btn primary" type="button" disabled={submitting} onClick={onConfirmSubmit}>
                <ButtonSpinner loading={submitting}>Yes, Submit</ButtonSpinner>
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
