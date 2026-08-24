import { useEffect, lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import { authCheckStarted, credentialsReceived, sessionCleared, selectAuthStatus, selectRoleCode } from '../features/auth/authSlice';
import * as authApi from '../api/authApi';
import ProtectedRoute from '../components/common/ProtectedRoute';
import ProtectedLayout from '../components/layout/ProtectedLayout';
import { FullPageSpinner } from '../components/loading/Spinner';
import ErrorBoundary from '../components/error/ErrorBoundary';
import NotFoundPage from '../components/error/NotFoundPage';
import { ExamSessionProvider } from '../features/exam/ExamSessionProvider';

// Eager: the auth screens. These are the first thing a staff user sees, so lazy-loading them
// would add a network round trip to the critical path for no benefit.
import Login from '../features/auth/Login';
import ForgotPassword from '../features/auth/ForgotPassword';
import OtpVerification from '../features/auth/OtpVerification';
import LoggedOut from '../features/auth/LoggedOut';

// Everything below is code-split. The whole app used to build as one 561 kB bundle, which meant
// a candidate opening their assessment link downloaded the entire staff application - dashboard,
// question bank, user management, audit log - before their exam would render, and a staff user
// downloaded the exam portal and its webcam machinery. Neither ever uses the other's code.
//
// Splitting by route group rather than per page: these pages share enough (tables, modals, the
// api layer) that finer granularity mostly produces chunks that are always fetched together.

// --- staff application ---
const Dashboard = lazy(() => import('../pages/Dashboard'));
const Profile = lazy(() => import('../pages/Profile'));
const BatchList = lazy(() => import('../pages/batches/BatchList'));
const BatchDetail = lazy(() => import('../pages/batches/BatchDetail'));
const BatchWizard = lazy(() => import('../features/batches/BatchWizard'));
const AllCandidates = lazy(() => import('../pages/candidates/AllCandidates'));
const CandidateDetail = lazy(() => import('../pages/candidates/CandidateDetail'));
const QuestionBank = lazy(() => import('../pages/questions/QuestionBank'));
const QuestionUpload = lazy(() => import('../pages/questions/QuestionUpload'));
const UserManagement = lazy(() => import('../pages/users/UserManagement'));
const EditUser = lazy(() => import('../pages/users/EditUser'));
const AuditLogs = lazy(() => import('../pages/audit/AuditLogs'));

// --- candidate exam portal ---
const ExamVerify = lazy(() => import('../pages/exam/ExamVerify'));
const ExamFullscreenGate = lazy(() => import('../pages/exam/ExamFullscreenGate'));
const ExamCameraPermission = lazy(() => import('../pages/exam/ExamCameraPermission'));
const ExamInstructions = lazy(() => import('../pages/exam/ExamInstructions'));
const ExamIdVerify = lazy(() => import('../pages/exam/ExamIdVerify'));
const ExamAttemptPage = lazy(() => import('../pages/exam/ExamAttemptPage'));

// --- footer pages ---
// No auth requirement: the footer that links here renders on every screen, staff console and
// candidate exam portal alike, logged in or not.
const HelpSupport = lazy(() => import('../pages/support/HelpSupport'));
const PrivacyPolicy = lazy(() => import('../pages/legal/PrivacyPolicy'));

// Wraps the candidate exam-taking routes in their own local session context - deliberately
// NOT ProtectedRoute/ProtectedLayout, which assume a logged-in staff user.
function ExamPortalLayout() {
  return (
    <ExamSessionProvider>
      <Outlet />
    </ExamSessionProvider>
  );
}

function RoleHome() {
  const roleCode = useSelector(selectRoleCode);
  if (roleCode === 'admin') return <Navigate to="/admin/dashboard" replace />;
  if (roleCode === 'ta') return <Navigate to="/ta/dashboard" replace />;
  return <Navigate to="/login" replace />;
}

export default function AppRouter() {
  const dispatch = useDispatch();
  const status = useSelector(selectAuthStatus);

  useEffect(() => {
    dispatch(authCheckStarted());
    authApi
      .refresh()
      .then((data) => dispatch(credentialsReceived(data)))
      .catch(() => dispatch(sessionCleared()));
  }, [dispatch]);

  // App boot: the session refresh decides which routes even exist for this user, so nothing
  // page-shaped can be skeletoned yet. A centred spinner is the honest indicator.
  if (status === 'idle' || status === 'loading') {
    return <FullPageSpinner label="Starting TalentGate" />;
  }

  return (
    // Wraps the whole routed tree: any unexpected render error below this becomes the 500 page
    // rather than a blank white screen. It also catches a failed chunk fetch, which is what a
    // lazy import rejects with when a deploy has replaced the assets mid-session.
    <ErrorBoundary>
    <BrowserRouter>
      {/* One Suspense boundary around the routes rather than per route: a route change swaps
          the whole page anyway, so a single fallback is what the user would see either way. */}
      <Suspense fallback={<FullPageSpinner label="Loading" />}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/verify-otp" element={<OtpVerification />} />
        <Route path="/logged-out" element={<LoggedOut />} />
        <Route path="/help" element={<HelpSupport />} />
        <Route path="/privacy" element={<PrivacyPolicy />} />

        <Route element={<ExamPortalLayout />}>
          <Route path="/t/:token" element={<ExamVerify />} />
          <Route path="/t/:token/fullscreen" element={<ExamFullscreenGate />} />
          <Route path="/t/:token/camera" element={<ExamCameraPermission />} />
          <Route path="/t/:token/instructions" element={<ExamInstructions />} />
          <Route path="/t/:token/identity" element={<ExamIdVerify />} />
          <Route path="/t/:token/exam" element={<ExamAttemptPage />} />
        </Route>

        <Route element={<ProtectedRoute><ProtectedLayout /></ProtectedRoute>}>
          <Route
            path="/admin/dashboard"
            element={
              <ProtectedRoute allowedRoles={['admin']}>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route
            path="/ta/dashboard"
            element={
              <ProtectedRoute allowedRoles={['ta']}>
                <Dashboard />
              </ProtectedRoute>
            }
          />
          <Route path="/profile" element={<Profile />} />

          {/* Shared between Admin and TA - same page/component per the wireframe's design intent */}
          <Route path="/batches" element={<BatchList />} />
          <Route path="/batches/new" element={<BatchWizard />} />
          {/* Resuming an unfinished draft - the wizard, not Batch Details. */}
          <Route path="/batches/:id/continue" element={<BatchWizard />} />
          <Route path="/batches/:id" element={<BatchDetail />} />
          <Route path="/candidates" element={<AllCandidates />} />
          <Route path="/candidates/:id" element={<CandidateDetail />} />

          <Route
            path="/admin/question-bank"
            element={<ProtectedRoute allowedRoles={['admin']}><QuestionBank /></ProtectedRoute>}
          />
          {/* Bulk upload + validation is its own page, not a modal - the validation table is
              too wide and its rows expand too far to work inside a dialog. */}
          <Route
            path="/admin/question-bank/upload"
            element={<ProtectedRoute allowedRoles={['admin']}><QuestionUpload /></ProtectedRoute>}
          />
          <Route
            path="/admin/users"
            element={<ProtectedRoute allowedRoles={['admin']}><UserManagement /></ProtectedRoute>}
          />
          <Route
            path="/admin/users/:id"
            element={<ProtectedRoute allowedRoles={['admin']}><EditUser /></ProtectedRoute>}
          />
          {/* Admin-only: the audit log shows every user's activity, which is what makes it
              useful for oversight and why a Staffing User must not see it. Enforced on the
              server too (IsAdmin on the endpoint) - this route guard is convenience, not
              the control. */}
          <Route
            path="/admin/audit-logs"
            element={<ProtectedRoute allowedRoles={['admin']}><AuditLogs /></ProtectedRoute>}
          />
        </Route>

        <Route path="/" element={<RoleHome />} />
        {/* Unknown routes now show a real 404 instead of silently bouncing to "/". The previous
            redirect meant a mistyped URL looked like a login/dashboard redirect, giving the user
            no idea the address was wrong. */}
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
      </Suspense>
    </BrowserRouter>
    </ErrorBoundary>
  );
}
