import axios from "axios";
import { useAuthStore } from "../stores/authStore";

export const client = axios.create({ baseURL: "/api/v1" });

client.interceptors.request.use((config) => {
  const token = useAuthStore.getState().accessToken;
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

client.interceptors.response.use(
  (res) => res,
  async (error) => {
    const { config, response } = error;
    if (response?.status === 401 && config && !config._retry) {
      config._retry = true;
      const { refreshToken, setTokens, clearAuth } = useAuthStore.getState();
      if (refreshToken) {
        try {
          const { data } = await axios.post("/api/v1/auth/refresh", { refresh_token: refreshToken });
          setTokens(data.access_token);
          config.headers.Authorization = `Bearer ${data.access_token}`;
          return client(config);
        } catch {
          clearAuth();
        }
      } else {
        clearAuth();
      }
    }
    return Promise.reject(error);
  }
);