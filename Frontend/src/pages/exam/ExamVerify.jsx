import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import * as examApi from '../../api/examApi';
import { useExamSession } from '../../features/exam/examSessionContext';
import { formatDateTime } from '../../utils/datetime';
import BrandHeader from '../../components/layout/BrandHeader';
import BrandFooter from '../../components/layout/BrandFooter';

const DEAD_END_COPY = {
  invalid: {
    title: 'Link Not Recognized',
    body: 'This assessment link is invalid. Please use the exact link from your invitation email, or contact the Staffing team.',
  },
  // body is filled in from link_valid_from/link_valid_until once the landing response arrives -
  // see the effect below. Falls back to this generic wording if that data didn't come through.
  expired: {
    title: 'Link Expired',
    body: 'This assessment link has expired. Please contact the Staffing team for a new invitation.',
  },
  completed: {
    title: 'Assessment Already Completed',
    body: 'This assessment has already been submitted. The Staffing User will contact you regarding next steps.',
  },
  // body is filled in from opens_at once the landing response arrives - see the effect below.
  not_yet_open: {
    title: 'Assessment Not Open Yet',
    body: 'This assessment is not open yet. Please come back once the window has started.',
  },
};

export default function ExamVerify() {
  const { token } = useParams();
  const navigate = useNavigate();
  const { setLinkToken, setInstructions, applyAttemptToken, setSessionState } = useExamSession();
  // loading | form | invalid | expired | completed | not_yet_open
  const [status, setStatus] = useState('loading');
  const [opensAt, setOpensAt] = useState(null);
  const [linkWindow, setLinkWindow] = useState(null); // { from, until }, for the expired screen
  const [email, setEmail] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    setLinkToken(token);
    examApi
      .getTokenLanding(token)
      .then((data) => {
        setStatus(data.reason === 'ok' ? 'form' : data.reason);
        if (data.reason === 'not_yet_open') setOpensAt(data.opens_at);
        if (data.reason === 'expired') {
          setLinkWindow({ from: data.link_valid_from, until: data.link_valid_until });
        }
      })
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
      // opens_at, when present, means the window closed between landing and this submit (or
      // this endpoint was reached directly) - reuse the same dead-end screen rather than a
      // form error, since retrying the form can't succeed until the window actually opens.
      const opens = err.response?.data?.opens_at;
      if (opens) {
        setOpensAt(opens);
        setStatus('not_yet_open');
        return;
      }
      setError(err.response?.data?.detail || 'Something went wrong. Please try again.');
    } finally {
      setSubmitting(false);
    }
  }

  let deadEnd = DEAD_END_COPY[status];
  if (deadEnd && status === 'not_yet_open' && opensAt) {
    deadEnd = {
      ...deadEnd,
      body: `This assessment opens at ${formatDateTime(opensAt)}. Please come back then.`,
    };
  }
  if (deadEnd && status === 'expired' && linkWindow) {
    deadEnd = {
      ...deadEnd,
      body: `This assessment link was valid from ${formatDateTime(linkWindow.from)} to `
        + `${formatDateTime(linkWindow.until)}, and that window has now closed. Please contact `
        + 'the Staffing team for a new invitation.',
    };
  }

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
