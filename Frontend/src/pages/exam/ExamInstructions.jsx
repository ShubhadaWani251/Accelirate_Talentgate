import { useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useExamSession } from '../../features/exam/examSessionContext';
import RequireFullscreen from '../../features/exam/proctoring/RequireFullscreen';
import AadhaarLayoutDiagram from '../../features/exam/AadhaarLayoutDiagram';
import BrandHeader from '../../components/layout/BrandHeader';

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
              <li>Please keep your Aadhaar ready before proceeding — the assessment cannot start until it is successfully verified. You can either <b>photograph the card</b> (front side, with the <b>Aadhaar number and your date of birth</b> both in frame and no glare) or <b>upload a file</b> — a <b style={{ color: 'var(--brand-red)' }}>JPG, JPEG or PNG image only; PDF files are not accepted</b>. If you have an e-Aadhaar PDF, open it and upload a screenshot or photo of the front of the card. A <b>masked card</b> showing only the last 4 digits (XXXX XXXX 1234), like an e-Aadhaar or DigiLocker download, works too. If it isn't read correctly, you can retry as many times as needed
                {/* The two fields verification reads are easier to show than to describe, and
                    a candidate who sees the shape first is less likely to photograph the back
                    of the card or crop the number off. Same drawing as the invitation email. */}
                <div style={{ margin: '10px 0 4px' }}>
                  <AadhaarLayoutDiagram width={300} />
                </div>
              </li>
              <li>Please start the assessment at least 30 minutes before your assessment window closes, to allow sufficient time to complete it</li>
              <li><b style={{ color: 'var(--brand-red)' }}>Your camera and microphone must stay on for the entire assessment</b> for identity verification and continuous proctoring. Switching your camera off, or covering it, is treated the same as leaving the window - it earns a warning from the same three-warning allowance</li>
              <li>Do not read questions aloud or talk during the assessment - sustained talking is detected and treated as a violation. Brief background noise is fine</li>
              {/* Stated as an explicit allowed/not-allowed list because the object detector had
                  been flagging a sheet of rough-work paper, and a candidate cannot comply with a
                  rule they were never told. The not-allowed half matches
                  visionModels.FORBIDDEN_OBJECT_CATEGORIES exactly - if that list changes, this
                  sentence has to change with it. */}
              <li><b>Allowed on your desk:</b> blank paper and a pen for rough work, and a drink. <b style={{ color: 'var(--brand-red)' }}>Not allowed in view of your camera:</b> a mobile phone, a second laptop or monitor, a TV, or a remote. Keep any electronic device out of frame for the whole assessment</li>
              <li>Do not switch browser tabs, minimize, exit full-screen, or open other applications once the exam begins</li>
              {/* Stated precisely, because a candidate who is told "one warning" for everything
                  would reasonably feel misled when a Print Screen ends the attempt outright.
                  The split is defined server-side in exam_session.WARNABLE_REASONS, and the
                  signals named here are that set in plain words - if it changes, this changes.
                  The three-warning figure is exam_session.MAX_WARNINGS. */}
              <li><b style={{ color: 'var(--brand-red)' }}>This assessment is AI-proctored.</b> Your microphone is listened to continuously and your camera is checked throughout. Talking, looking away from the screen, your face leaving the frame, another person appearing behind you, and <b>any electronic device in view</b> - a phone, a second screen, a TV or a remote - are all detected automatically. <b style={{ color: 'var(--brand-red)' }}>You get up to three warnings</b> across all of these together. The fourth ends your attempt immediately and your answers are submitted as they are. Take the time to read each warning — there is no time limit on dismissing it, but your exam timer keeps running while it is open</li>
              <li>Keyboard shortcuts like Print Screen, F12 or Ctrl+U are <b>not warned at all</b> - they end your attempt <b>immediately, the first time you press them</b></li>
              {/* Stated explicitly because candidates routinely assume the opposite and leave
                  questions blank to avoid a penalty that does not exist. Accurate as written:
                  finalize_attempt scores a section as its count of correct answers, with no
                  deduction for a wrong one. */}
              <li>There is <b>no negative marking</b> - a wrong answer scores zero, exactly like an unanswered one, so there is nothing to lose by attempting every question</li>
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
    </div>
    </RequireFullscreen>
  );
}
