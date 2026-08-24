import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import * as examApi from '../../api/examApi';
import { useExamSession } from '../../features/exam/examSessionContext';
import BrandHeader from '../../components/layout/BrandHeader';
import BrandFooter from '../../components/layout/BrandFooter';

const DEAD_END_COPY = {
  invalid: {
    title: 'Link Not Recognized',
    body: 'This assessment link is invalid. Please use the exact link from your invitation email, or contact the Staffing team.',
  },
  expired: {
    title: 'Link Expired',
    body: 'This assessment link has expired. Please contact the Staffing team for a new invitation.',
  },
  completed: {
    title: 'Assessment Already Completed',
    body: 'This assessment has already been submitted. The Staffing User will contact you regarding next steps.',
  },
};

export default function ExamVerify() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { setLinkToken, setInstructions, applyAttemptToken, setSessionState } = useExamSession();
  const [status, setStatus] = useState('loading'); // loading | form | invalid | expired | completed
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setLinkToken(token);
    examApi
      .getTokenLanding(token)
      .then((data) => setStatus(data.reason === 'ok' ? 'form' : data.reason))
      .catch(() => setStatus('invalid'));
  }, [token, setLinkToken]);

  async function onSubmit(e) {
    e.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      const data = await examApi.verifyEmail(token, email);
      if (data.resume) {
        applyAttemptToken(data.attempt_token, token);
        setSessionState({ remaining_seconds: data.remaining_seconds, sections: data.sections });
        navigate(`/t/${token}/exam`);
      } else {
        setInstructions(data);
        // Camera/mic permission comes BEFORE full-screen on purpose: browsers force-exit
        // full-screen whenever a permission prompt appears, so asking first means full-screen is
        // never interrupted once entered.
        navigate(`/t/${token}/camera`);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  const deadEnd = DEAD_END_COPY[status];

  return (
    <div className="app-shell">
      <BrandHeader roleCode="candidate" />
      <div className="auth-shell">
        <div className="auth-card">
          {status === 'loading' && <div className="auth-sub">Loading…</div>}

          {deadEnd && (
            <>
              <h3>{deadEnd.title}</h3>
              <div className="auth-sub">{deadEnd.body}</div>
            </>
          )}

          {status === 'form' && (
            <>
              <h3>Confirm Your Details</h3>
              <div className="auth-sub">Enter the email address this assessment link was sent to.</div>

              {error && <div className="alert error">{error}</div>}

              <form onSubmit={onSubmit} noValidate>
                <div className="field">
                  <label htmlFor="email">Registered Email</label>
                  <input
                    id="email"
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                  />
                </div>
                <button className="btn primary block" type="submit" disabled={submitting}>
                  {submitting ? 'Checking…' : 'Continue'}
                </button>
              </form>
            </>
          )}
        </div>
      </div>
      <BrandFooter roleCode="candidate" />
    </div>
  );
}
