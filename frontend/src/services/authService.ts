import { apiClient } from '../lib/api/config';

export interface AuthUser {
  username: string;
  role: string;
}

export interface LoginCredentials {
  username: string;
  password: string;
}

interface LoginResponse {
  user: AuthUser;
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

  async me(): Promise<AuthUser> {
    const response = await apiClient.get<AuthUser>('/auth/me');
    return response.data;
  },
};
