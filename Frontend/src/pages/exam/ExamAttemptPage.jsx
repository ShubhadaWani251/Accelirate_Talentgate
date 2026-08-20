import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import * as examApi from '../../api/examApi';
import { useExamSession } from '../../features/exam/ExamSessionProvider';
import useExamTimer from '../../features/exam/timer/useExamTimer';
import useTabSwitchGuard from '../../features/exam/proctoring/useTabSwitchGuard';
import useFullscreenGuard from '../../features/exam/proctoring/useFullscreenGuard';
import useExamLockdown from '../../features/exam/proctoring/useExamLockdown';
import useSessionRecorder from '../../features/exam/webcam/useSessionRecorder';
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

export default function ExamAttemptPage() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { sessionState, setSessionState, restoreAttemptToken, mediaStreamRef } = useExamSession();

  const [view, setView] = useState('loading'); // loading | exam | result | terminated
  const [answers, setAnswers] = useState({});
  const [showConfirm, setShowConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState(null);
  const [terminationMessage, setTerminationMessage] = useState('');
  // Gates the actual question content behind a full-screen entry click - requestFullscreen()
  // needs a real user gesture, so it can't fire automatically on page load. Already true if the
  // candidate is arriving from the earlier ExamFullscreenGate screen (the normal path) - this
  // gate is really only reached on a refresh/resume, since a page reload always exits
  // full-screen. A browser with no Fullscreen API support (rare) skips the gate entirely.
  const [fullscreenReady, setFullscreenReady] = useState(
    !FULLSCREEN_SUPPORTED || isFullscreen()
  );
  // The clock is started by the server on POST /exam/begin/, which only happens once the
  // candidate is genuinely in the exam window (full-screen satisfied). Questions and the
  // countdown are withheld until that call returns, so the timer can never be shown - or run -
  // before the server considers the exam started.
  const [begun, setBegun] = useState(false);
  const beginRequestedRef = useRef(false);

  useEffect(() => {
    if (sessionState) {
      setAnswers(flattenAnswers(sessionState.sections));
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
        .terminateAttempt(state.reason)
        .then((data) => setTerminationMessage(data.detail))
        .catch(() => setTerminationMessage(
          // Deliberately cause-agnostic: this only runs when the terminate call itself failed, so
          // the real reason is unknown here. It must NOT claim a specific cause (it previously
          // asserted camera/mic loss, which was simply wrong for e.g. a devtools attempt).
          'Your assessment was ended and could not be reported to the server. '
          + 'Please contact the Staffing team.'
        ))
        .finally(() => setView('terminated'));
    }, REASON_SETTLE_MS);
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
      .catch(() => {
        // Already-closed/expired attempts 401 here; auth-layer handling covers those. Allow a
        // retry rather than latching, so a transient network blip isn't a dead end.
        beginRequestedRef.current = false;
      });
  }, [view, fullscreenReady, setSessionState]);

  // Only counts down once the server has actually started the exam - the `begun` gate also stops
  // it from ticking 0 -> onExpire and auto-submitting a blank paper before the exam starts.
  const timer = useExamTimer(sessionState?.remaining_seconds ?? 0, finishExam, begun);
  useTabSwitchGuard(view === 'exam', onViolation);
  useFullscreenGuard(examActive, onViolation);
  useExamLockdown(examActive, onViolation);
  useSessionRecorder(mediaStreamRef.current, examActive);

  // "System issue" - the camera/mic feed the recorder depends on disappearing mid-exam (device
  // unplugged, OS revokes permission, laptop lid closed). Not the candidate's fault, so
  // finalize_attempt/is_violation_reason on the backend keeps this out of their violation record
  // even though the attempt still has to end - the recording can't continue without it.
  useEffect(() => {
    if (!examActive) return undefined;
    const stream = mediaStreamRef.current;
    if (!stream) return undefined;
    const tracks = stream.getTracks();
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

  function onSelectOption(questionId, option) {
    setAnswers((prev) => ({ ...prev, [questionId]: option }));
    examApi.saveAnswer(questionId, option).catch(() => {});
  }

  const unansweredCount = useMemo(
    () => Object.values(answers).filter((v) => !v).length,
    [answers]
  );

  async function onConfirmSubmit() {
    setShowConfirm(false);
    await finishExam();
  }

  if (view === 'loading') return null;
  if (view === 'terminated') return <ExamTerminated message={terminationMessage} />;
  if (view === 'result') return <ExamResult result={result} />;

  if (!fullscreenReady) {
    return (
      <div className="app-shell">
        <BrandHeader roleCode="candidate" />
        <div className="auth-shell">
          <div className="auth-card" style={{ textAlign: 'center' }}>
            <h3>Enter Full-Screen to Begin</h3>
            <div className="auth-sub">
              The assessment runs in full-screen mode. Exiting full-screen, switching tabs, or
              leaving this window once started will end your attempt automatically and be
              logged — per the integrity rules shown earlier.
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
            <h3>Starting your assessment…</h3>
            <div className="auth-sub">Your timer begins now. Please don't close this window.</div>
          </div>
        </div>
        <BrandFooter roleCode="candidate" />
      </div>
    );
  }

  const lowTime = timer.remaining <= 300; // last 5 minutes

  return (
    <div className="app-shell">
      <BrandHeader roleCode="candidate" />
      <div style={{ flex: 1, padding: '20px 16px', maxWidth: 760, margin: '0 auto', width: '100%' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
          <h3 style={{ margin: 0 }}>Assessment — All Questions</h3>
          <div className={`timer-badge${lowTime ? ' low-time' : ''}`}>⏱ {timer.formatted} remaining</div>
        </div>

        {sessionState.sections.map((section) => (
          <div key={section.key}>
            <div className="section-marker">
              {section.label} ({section.questions.length} question{section.questions.length === 1 ? '' : 's'})
            </div>
            {section.questions.map((q, idx) => (
              <div className="q-card" key={q.question_id}>
                <div className="q-num">Question {idx + 1}</div>
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
          </div>
        ))}

        <div className="btn-row" style={{ margin: '18px 0' }}>
          <button className="btn danger" type="button" onClick={() => setShowConfirm(true)}>
            Submit Exam
          </button>
        </div>
      </div>
      <BrandFooter roleCode="candidate" />

      {showConfirm && (
        <div className="modal-overlay">
          <div className="modal-box">
            <h4>Submit Assessment?</h4>
            <p>
              {unansweredCount > 0
                ? `${unansweredCount} of ${Object.keys(answers).length} questions are still unanswered. `
                : ''}
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
