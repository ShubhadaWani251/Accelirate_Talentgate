import { useCallback, useRef, useState } from 'react';
import { setAttemptToken as setAxiosAttemptToken } from '../../api/examAxiosClient';
import { ExamSessionContext } from './examSessionContext';

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
  // The candidate's face embedding, captured once at identity-verification time (see
  // ExamIdVerify.jsx) and compared against the live feed throughout the exam
  // (useFaceIdentityGuard.js). Wiped by a page reload exactly like mediaStreamRef is - that guard
  // has its own narrow fallback for that case, see its own docstring.
  const faceEmbeddingRef = useRef(null);

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
    faceEmbeddingRef,
  };

  return <ExamSessionContext.Provider value={value}>{children}</ExamSessionContext.Provider>;
}
