import { apiClient } from '../lib/api/config';
import type { DemoQuotaStatus } from '../types/api';

export interface AuthUser {
  username: string;
  role: string;
  quota?: DemoQuotaStatus | null;
}

export interface LoginCredentials {
  username: string;
  password: string;
}

interface LoginResponse {
  user: AuthUser;
  message: string;
}

interface DemoLoginResponse {
  user: AuthUser;
  quota: DemoQuotaStatus;
  message: string;
}

export const authService = {
  async login(credentials: LoginCredentials): Promise<AuthUser> {
    const response = await apiClient.post<LoginResponse>('/auth/login', credentials);
    return response.data.user;
  },

  async logout(): Promise<void> {
    await apiClient.post('/auth/logout');
  },

  async startDemo(): Promise<AuthUser> {
    const response = await apiClient.post<DemoLoginResponse>('/auth/demo');
    return {
      ...response.data.user,
      quota: response.data.quota,
    };
  },

  async me(): Promise<AuthUser> {
    const response = await apiClient.get<AuthUser>('/auth/me');
    return response.data;
  },
};
