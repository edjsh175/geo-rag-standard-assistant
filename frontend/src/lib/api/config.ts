import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios';

export const API_UNAUTHORIZED_EVENT = 'geoai:unauthorized';

const envApiBaseUrl = import.meta.env.VITE_API_URL?.trim();

const isLoopbackOrigin = (value: string): boolean =>
  /^https?:\/\/(?:localhost|127(?:\.\d{1,3}){3}|0\.0\.0\.0)(?::\d+)?(?:\/|$)/i.test(value);

const isLoopbackPage =
  typeof window !== 'undefined' &&
  /^(?:localhost|127(?:\.\d{1,3}){3}|0\.0\.0\.0)$/i.test(window.location.hostname);

const API_BASE_URL =
  envApiBaseUrl && (!isLoopbackOrigin(envApiBaseUrl) || isLoopbackPage)
    ? envApiBaseUrl
    : '/api';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
  withCredentials: true,
  headers: {
    'Content-Type': 'application/json',
  },
});

apiClient.interceptors.request.use(
  (config: InternalAxiosRequestConfig) => config,
  (error: AxiosError) => Promise.reject(error)
);

apiClient.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    console.error('API request error:', error);

    if (
      typeof window !== 'undefined' &&
      error.response?.status === 401 &&
      !String(error.config?.url || '').includes('/auth/')
    ) {
      window.dispatchEvent(new CustomEvent(API_UNAUTHORIZED_EVENT));
    }

    if (error.response) {
      const { status, data } = error.response;
      console.error(`API error ${status}:`, data);
    } else if (error.request) {
      console.error('Network error: no response from server.');
    } else {
      console.error('Request config error:', error.message);
    }

    return Promise.reject(error);
  }
);

export { apiClient };
