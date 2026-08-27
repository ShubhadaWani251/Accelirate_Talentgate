import { createContext, useContext } from 'react';

// The context and its accessor hook live here rather than beside the provider component so that
// ExamSessionProvider.jsx exports nothing but a component. A file mixing component and
// non-component exports loses Vite's Fast Refresh for the whole module, and this one is imported
// by every screen in the exam flow (react-refresh/only-export-components).
//
// Local Context, deliberately NOT the app's Redux store (app/store.js) - this flow is short-lived
// and single-session and never shares state with the staff app shell a candidate never sees.
export const ExamSessionContext = createContext(null);

export function useExamSession() {
  const ctx = useContext(ExamSessionContext);
  if (!ctx) throw new Error('useExamSession must be used within ExamSessionProvider');
  return ctx;
}
