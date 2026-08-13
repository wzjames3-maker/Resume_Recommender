import axios from "axios";

import { client } from "./client";

export function login(email: string, password: string) {
  return client.post("/auth/login", { email, password }).then((r) => r.data);
}

export function register(email: string, password: string, nickname: string) {
  return client.post("/auth/register", { email, password, nickname }).then((r) => r.data);
}

export function getMe(accessToken: string) {
  return client.get("/users/me", { headers: { Authorization: `Bearer ${accessToken}` } }).then((r) => r.data);
}

export function logout(accessToken: string, refreshToken: string) {
  return axios.post("/api/v1/auth/logout", { refresh_token: refreshToken }, { headers: { Authorization: `Bearer ${accessToken}` } });
}

export function updateMe(accessToken: string, nickname: string) {
  return client.put("/users/me", { nickname }, { headers: { Authorization: `Bearer ${accessToken}` } }).then((r) => r.data);
}