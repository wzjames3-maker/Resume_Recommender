import { client } from "./client";

export function list() {
  return client.get("/workspaces").then((r) => r.data.items);
}

export function create(name: string) {
  return client.post("/workspaces", { name }).then((r) => r.data);
}

export function getDetail(wsId: number) {
  return client.get(`/workspaces/${wsId}`).then((r) => r.data);
}

export function remove(wsId: number) {
  return client.delete(`/workspaces/${wsId}`).then((r) => r.data);
}

export function inviteMember(wsId: number, email: string, role: string) {
  return client.post(`/workspaces/${wsId}/members`, { email, role }).then((r) => r.data);
}

export function updateMemberRole(wsId: number, targetUserId: number, role: string) {
  return client.patch(`/workspaces/${wsId}/members/${targetUserId}`, { role }).then((r) => r.data);
}

export function removeMember(wsId: number, targetUserId: number) {
  return client.delete(`/workspaces/${wsId}/members/${targetUserId}`).then((r) => r.data);
}

export function getUsage(wsId: number) {
  return client.get(`/workspaces/${wsId}/usage`).then((r) => r.data);
}