import type { ReactElement } from 'react';
import { Navigate } from 'react-router-dom';

import BootScreen from '../components/BootScreen';
import { useAuth } from './AuthProvider';

export default function ProtectedRoute({ children }: { children: ReactElement }) {
  const { status } = useAuth();

  if (status === 'booting') {
    return (
      <BootScreen
        status="正在恢复登录会话"
        detail="正在确认管理员身份与安全会话，请稍候。"
      />
    );
  }

  if (status !== 'authenticated') {
    return <Navigate to="/login" replace />;
  }

  return children;
}
