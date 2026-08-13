import { create } from "zustand";
import { persist } from "zustand/middleware";
import * as authApi from "../api/auth";

interface AuthState {
  accessToken: string | null;
  refreshToken: string | null;
  user: { id: number; email: string; nickname: string } | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  clearAuth: () => void;
  setTokens: (accessToken: string) => void;
  setUser: (user: any) => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      accessToken: null,
      refreshToken: null,
      user: null,
      isAuthenticated: false,
      login: async (email, password) => {
        const { access_token, refresh_token } = await authApi.login(email, password);
        const user = await authApi.getMe(access_token);
        set({ accessToken: access_token, refreshToken: refresh_token, user, isAuthenticated: true });
      },
      logout: async () => {
        const { accessToken, refreshToken } = get();
        if (accessToken && refreshToken) {
          try {
            await authApi.logout(accessToken, refreshToken);
          } catch {
            // 忽略登出接口失败，本地状态仍清空
          }
        }
        set({ accessToken: null, refreshToken: null, user: null, isAuthenticated: false });
      },
      clearAuth: () => set({ accessToken: null, refreshToken: null, user: null, isAuthenticated: false }),
      setTokens: (accessToken) => set({ accessToken }),
      setUser: (user) => set({ user }),
    }),
    {
      name: "auth-storage",
      partialize: (s) => ({ accessToken: s.accessToken, refreshToken: s.refreshToken, user: s.user, isAuthenticated: s.isAuthenticated }),
    }
  )
);