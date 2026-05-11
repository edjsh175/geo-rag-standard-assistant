import { BrowserRouter, Route, Routes } from 'react-router-dom';

import App from './App';
import { AuthProvider, useAuth } from './auth/AuthProvider';
import ProtectedRoute from './auth/ProtectedRoute';
import BootScreen from './components/BootScreen';
import LoginPage from './pages/LoginPage';

function LoginRoute() {
  const { status } = useAuth();

  if (status === 'booting') {
    return (
      <BootScreen
        status="正在恢复登录会话"
        detail="正在确认管理员身份与历史会话，请稍候。"
      />
    );
  }

  return <LoginPage />;
}

export default function RootApp() {
  return (
    <AuthProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<LoginRoute />} />
          <Route
            path="/*"
            element={
              <ProtectedRoute>
                <App />
              </ProtectedRoute>
            }
          />
        </Routes>
      </BrowserRouter>
    </AuthProvider>
  );
}
