import { client } from "./client";

export async function listJobs(wsId: number, params: Record<string, unknown> = {}) {
  return client.get(`/workspaces/${wsId}/jobs`, { params }).then((r) => r.data);
}

export async function getJob(wsId: number, id: number) {
  return client.get(`/workspaces/${wsId}/jobs/${id}`).then((r) => r.data);
}

export async function createJob(wsId: number, body: unknown) {
  return client.post(`/workspaces/${wsId}/jobs`, body).then((r) => r.data);
}

export async function updateJob(wsId: number, id: number, body: unknown) {
  return client.patch(`/workspaces/${wsId}/jobs/${id}`, body).then((r) => r.data);
}

export async function overrideJobRequirement(wsId: number, id: number, body: unknown) {
  return client.post(`/workspaces/${wsId}/jobs/${id}/overrides`, body).then((r) => r.data);
}

export async function listJobRevisions(wsId: number, id: number) {
  return client.get(`/workspaces/${wsId}/jobs/${id}/revisions`).then((r) => r.data);
}

export async function jobMatches(wsId: number, id: number, limit = 20) {
  return client.get(`/workspaces/${wsId}/jobs/${id}/matches`, { params: { limit } }).then((r) => r.data);
}