import { createContext, useCallback, useContext, useRef, useState } from 'react';
import { setAttemptToken as setAxiosAttemptToken } from '../../api/examAxiosClient';

// Local Context, deliberately NOT the app's Redux store (app/store.js) - this flow is
// short-lived and single-session and never shares state with the staff app shell a candidate
// never sees.
const ExamSessionContext = createContext(null);

function storageKey(linkToken) {
  return `examAttemptToken:${linkToken}`;
}

export function ExamSessionProvider({ children }) {
  const [linkToken, setLinkToken] = useState(null);
  const [instructions, setInstructions] = useState(null);
  const [sessionState, setSessionState] = useState(null); // {remaining_seconds, sections}
  // The getUserMedia stream captured on the dedicated camera-permission screen, reused (not
  // re-prompted for) by both the identity-capture screen and the continuous recorder once the
  // exam starts. noVideo marks the dev-only audio-fallback path (see useCameraStream.js).
  const mediaStreamRef = useRef(null);
  const [noVideo, setNoVideo] = useState(false);

  const applyAttemptToken = useCallback((token, forLinkToken) => {
    setAxiosAttemptToken(token);
    if (forLinkToken) {
      if (token) sessionStorage.setItem(storageKey(forLinkToken), token);
      else sessionStorage.removeItem(storageKey(forLinkToken));
    }
  }, []);

  const restoreAttemptToken = useCallback((forLinkToken) => {
    const stored = sessionStorage.getItem(storageKey(forLinkToken));
    setAxiosAttemptToken(stored);
    return stored;
  }, []);

  const value = {
    linkToken, setLinkToken,
    instructions, setInstructions,
    sessionState, setSessionState,
    applyAttemptToken, restoreAttemptToken,
    mediaStreamRef, noVideo, setNoVideo,
  };

  return <ExamSessionContext.Provider value={value}>{children}</ExamSessionContext.Provider>;
}

export function useExamSession() {
  const ctx = useContext(ExamSessionContext);
  if (!ctx) throw new Error('useExamSession must be used within ExamSessionProvider');
  return ctx;
}
