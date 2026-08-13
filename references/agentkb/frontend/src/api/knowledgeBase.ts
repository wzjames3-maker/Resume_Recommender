import { client } from "./client";

export function list(wsId: number) {
  return client.get(`/workspaces/${wsId}/knowledge-bases`).then((r) => r.data.items);
}

export function create(wsId: number, body: { name: string; description?: string }) {
  return client.post(`/workspaces/${wsId}/knowledge-bases`, body).then((r) => r.data);
}

export function get(kbId: number) {
  return client.get(`/knowledge-bases/${kbId}`).then((r) => r.data);
}

export function update(kbId: number, body: { name?: string; description?: string }) {
  return client.put(`/knowledge-bases/${kbId}`, body).then((r) => r.data);
}

export function remove(kbId: number) {
  return client.delete(`/knowledge-bases/${kbId}`).then((r) => r.data);
}