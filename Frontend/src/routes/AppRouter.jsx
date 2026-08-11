import { useEffect } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import { authCheckStarted, credentialsReceived, sessionCleared, selectAuthStatus, selectRoleCode } from '../features/auth/authSlice';
import * as authApi from '../api/authApi';
import Login from '../features/auth/Login';
import ForgotPassword from '../features/auth/ForgotPassword';
import OtpVerification from '../features/auth/OtpVerification';
import ProtectedRoute from '../components/common/ProtectedRoute';
import ProtectedLayout from '../components/layout/ProtectedLayout';
import Dashboard from '../pages/Dashboard';
import Profile from '../pages/Profile';
import BatchList from '../pages/batches/BatchList';
import BatchDetail from '../pages/batches/BatchDetail';
import BatchWizard from '../features/batches/BatchWizard';
import AllCandidates from '../pages/candidates/AllCandidates';
import CandidateDetail from '../pages/candidates/CandidateDetail';

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
          <Route path="/batches/:id" element={<BatchDetail />} />
          <Route path="/candidates" element={<AllCandidates />} />
          <Route path="/candidates/:id" element={<CandidateDetail />} />
        </Route>

        <Route path="/" element={<RoleHome />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
