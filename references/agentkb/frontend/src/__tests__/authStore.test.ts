import { describe, it, expect, vi, beforeEach } from "vitest";
import { useAuthStore } from "../stores/authStore";

vi.mock("../api/auth", () => ({
  login: vi.fn().mockResolvedValue({ access_token: "at", refresh_token: "rt" }),
  getMe: vi.fn().mockResolvedValue({ id: 1, email: "a@b.com", nickname: "A" }),
  logout: vi.fn().mockResolvedValue({}),
}));

describe("authStore", () => {
  beforeEach(() => useAuthStore.getState().clearAuth());
  it("login sets isAuthenticated", async () => {
    await useAuthStore.getState().login("a@b.com", "secret123");
    expect(useAuthStore.getState().isAuthenticated).toBe(true);
  });
  it("clearAuth wipes tokens without calling logout API", async () => {
    const { login, logout } = await import("../api/auth");
    await useAuthStore.getState().login("a@b.com", "secret123");
    useAuthStore.getState().clearAuth();
    expect(useAuthStore.getState().accessToken).toBeNull();
    expect(useAuthStore.getState().refreshToken).toBeNull();
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(logout).not.toHaveBeenCalled();
  });
});