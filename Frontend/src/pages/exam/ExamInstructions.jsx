import { useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useExamSession } from '../../features/exam/examSessionContext';
import RequireFullscreen from '../../features/exam/proctoring/RequireFullscreen';
import BrandHeader from '../../components/layout/BrandHeader';
import BrandFooter from '../../components/layout/BrandFooter';

export default function ExamInstructions() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { instructions } = useExamSession();

  // A direct refresh loses in-memory instructions data (it isn't persisted) - send the
  // candidate back through the verify step rather than rendering a blank page.
  useEffect(() => {
    if (!instructions) navigate(`/t/${token}`, { replace: true });
  }, [instructions, navigate, token]);

  if (!instructions) return null;

  return (
    <RequireFullscreen>
    <div className="app-shell">
      <BrandHeader roleCode="candidate" />
      <div className="auth-shell">
        <div className="auth-card" style={{ maxWidth: 480 }}>
          <h3>Before You Begin</h3>
          <div className="auth-sub">Hello {instructions.candidate_name} — {instructions.batch_name}</div>

          <div className="card">
            <div className="box-label">Assessment Details</div>
            <div style={{ fontSize: 12.5, lineHeight: 1.8 }}>
              Duration: <b>{instructions.exam_duration_minutes} minutes</b> &nbsp;·&nbsp;
              Questions: <b>{instructions.total_questions}</b>
              <br />
              Sections: {instructions.sections.map((s) => s.label).join(', ')}
              {/* The section cutoff is deliberately NOT shown. It is a figure the TA can
                  revise after seeing how a cohort scored (see BatchDetailView's
                  EDITABLE_AFTER_DRAFT), so a number printed here could be out of date by the
                  time results are graded. */}
            </div>
          </div>

          <div className="card">
            <div className="box-label">Please Note</div>
            {/* Numbered rather than bulleted: these are rules a candidate may need to refer
                back to ("rule 5 said..."), and an ordered list gives each one a handle. */}
            <ol style={{ fontSize: 12.5, margin: 0, paddingLeft: 20, lineHeight: 1.8 }}>
              <li>Please be prepared with your government ID document before proceeding</li>
              <li>Your camera and microphone stay on for identity verification and continuous proctoring throughout the assessment. <b>Switching your camera off, or covering it, is treated the same as leaving the window</b> - one warning, then the attempt ends</li>
              <li>You're now in full-screen mode for the rest of this assessment</li>
              <li>Do not switch browser tabs, minimize, exit full-screen, or open other applications once the exam begins</li>
              {/* Stated precisely, because a candidate who is told "one warning" for everything
                  would reasonably feel misled when a Print Screen ends the attempt outright.
                  The split is defined server-side in exam_session.WARNABLE_REASONS. */}
              <li><b>You get one warning</b> the first time you leave the assessment window. The second time, your attempt ends immediately and your answers are submitted as they are</li>
              <li>Keyboard shortcuts like Print Screen, F12 or Ctrl+U end your attempt <b>immediately, with no warning</b></li>
              <li>Every such event is logged and shown to the Staffing team, with the specific reason shown to you too</li>
              {/* Stated explicitly because candidates routinely assume the opposite and leave
                  questions blank to avoid a penalty that does not exist. Accurate as written:
                  finalize_attempt scores a section as its count of correct answers, with no
                  deduction for a wrong one. */}
              <li>There is <b>no negative marking</b> - a wrong answer scores zero, exactly like an unanswered one, so there is nothing to lose by attempting every question</li>
              <li>The timer cannot be paused once started</li>
              <li>You may submit the assessment early at any time from the Submit button</li>
              <li>You will see only your section-wise marks at the end</li>
            </ol>
          </div>

          <button
            className="btn primary block"
            type="button"
            onClick={() => navigate(`/t/${token}/identity`)}
          >
            Continue to ID Verification
          </button>
        </div>
      </div>
      <BrandFooter roleCode="candidate" />
    </div>
    </RequireFullscreen>
  );
}
