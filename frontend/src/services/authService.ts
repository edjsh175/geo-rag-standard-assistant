import { apiGet, apiPost } from '../lib/api/contractClient';
import type { components } from '../lib/api/generated/schema';

export type AuthUser = components['schemas']['AuthUserResponse'];
export type LoginCredentials = components['schemas']['LoginRequest'];
type LoginResponse = components['schemas']['LoginResponse'];
type DemoLoginResponse = components['schemas']['DemoLoginResponse'];

export const authService = {
  async login(credentials: LoginCredentials): Promise<AuthUser> {
    const response: LoginResponse = await apiPost('/api/auth/login', credentials);
    return response.user;
  },

  async logout(): Promise<void> {
    await apiPost('/api/auth/logout');
  },

  async startDemo(): Promise<AuthUser> {
    const response: DemoLoginResponse = await apiPost('/api/auth/demo');
    return {
      ...response.user,
      quota: response.quota,
    };
  },

  async me(): Promise<AuthUser> {
    return await apiGet('/api/auth/me');
  },
};
