import axios, { AxiosError, type InternalAxiosRequestConfig } from 'axios';

const API_BASE_URL = import.meta.env.VITE_API_URL ?? '/api';

const apiClient = axios.create({
  baseURL: API_BASE_URL,
  timeout: 30000,
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
