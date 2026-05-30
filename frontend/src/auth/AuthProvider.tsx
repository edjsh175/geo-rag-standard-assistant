import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import { AxiosError } from 'axios';

import { API_UNAUTHORIZED_EVENT } from '../lib/api/config';
import { authService, type AuthUser, type LoginCredentials } from '../services/authService';
import type { DemoQuotaStatus } from '../types/api';

type AuthStatus = 'booting' | 'anonymous' | 'authenticated';

interface AuthContextValue {
  status: AuthStatus;
  user: AuthUser | null;
  login: (credentials: LoginCredentials) => Promise<AuthUser>;
  startDemo: () => Promise<AuthUser>;
  logout: () => Promise<void>;
  refreshSession: () => Promise<void>;
  updateQuota: (quota: DemoQuotaStatus) => void;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function isUnauthorized(error: unknown): boolean {
  return error instanceof AxiosError && error.response?.status === 401;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>('booting');
  const [user, setUser] = useState<AuthUser | null>(null);

  const refreshSession = useCallback(async () => {
    setStatus('booting');
    try {
      const nextUser = await authService.me();
      setUser(nextUser);
      setStatus('authenticated');
    } catch (error) {
      if (!isUnauthorized(error)) {
        console.error('Session refresh failed:', error);
      }
      setUser(null);
      setStatus('anonymous');
    }
  }, []);

  useEffect(() => {
    refreshSession();

    const handleUnauthorized = () => {
      setUser(null);
      setStatus('anonymous');
    };

    window.addEventListener(API_UNAUTHORIZED_EVENT, handleUnauthorized);
    return () => {
      window.removeEventListener(API_UNAUTHORIZED_EVENT, handleUnauthorized);
    };
  }, [refreshSession]);

  const login = useCallback(async (credentials: LoginCredentials) => {
    const nextUser = await authService.login(credentials);
    setUser(nextUser);
    setStatus('authenticated');
    return nextUser;
  }, []);

  const startDemo = useCallback(async () => {
    const nextUser = await authService.startDemo();
    setUser(nextUser);
    setStatus('authenticated');
    return nextUser;
  }, []);

  const logout = useCallback(async () => {
    try {
      await authService.logout();
    } finally {
      setUser(null);
      setStatus('anonymous');
    }
  }, []);

  const updateQuota = useCallback((quota: DemoQuotaStatus) => {
    setUser((current) => (current ? { ...current, quota } : current));
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({
      status,
      user,
      login,
      startDemo,
      logout,
      refreshSession,
      updateQuota,
    }),
    [login, logout, refreshSession, startDemo, status, updateQuota, user]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error('useAuth must be used within an AuthProvider.');
  }
  return value;
}
