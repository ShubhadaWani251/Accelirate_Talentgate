import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate, Outlet } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import { authCheckStarted, credentialsReceived, sessionCleared, selectAuthStatus, selectRoleCode } from '../features/auth/authSlice';
import * as authApi from '../api/authApi';
import Login from '../features/auth/Login';
import ForgotPassword from '../features/auth/ForgotPassword';
import OtpVerification from '../features/auth/OtpVerification';
import LoggedOut from '../features/auth/LoggedOut';
import ProtectedRoute from '../components/common/ProtectedRoute';
import ProtectedLayout from '../components/layout/ProtectedLayout';
import Dashboard from '../pages/Dashboard';
import Profile from '../pages/Profile';
import BatchList from '../pages/batches/BatchList';
import BatchDetail from '../pages/batches/BatchDetail';
import BatchWizard from '../features/batches/BatchWizard';
import AllCandidates from '../pages/candidates/AllCandidates';
import CandidateDetail from '../pages/candidates/CandidateDetail';
import QuestionBank from '../pages/questions/QuestionBank';
import QuestionUpload from '../pages/questions/QuestionUpload';
import UserManagement from '../pages/users/UserManagement';
import EditUser from '../pages/users/EditUser';
import { ExamSessionProvider } from '../features/exam/ExamSessionProvider';
import ExamVerify from '../pages/exam/ExamVerify';
import ExamFullscreenGate from '../pages/exam/ExamFullscreenGate';
import ExamCameraPermission from '../pages/exam/ExamCameraPermission';
import ExamInstructions from '../pages/exam/ExamInstructions';
import ExamIdVerify from '../pages/exam/ExamIdVerify';
import ExamAttemptPage from '../pages/exam/ExamAttemptPage';

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

  if (status === 'idle' || status === 'loading') {
    return <div className="loading-splash">Loading TalentGate…</div>;
  }

  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        <Route path="/verify-otp" element={<OtpVerification />} />
        <Route path="/logged-out" element={<LoggedOut />} />

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
        </Route>

        <Route path="/" element={<RoleHome />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
