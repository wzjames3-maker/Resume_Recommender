import { client } from "./client";

export async function listCandidates(wsId: number, params: Record<string, unknown> = {}) {
  return client.get(`/workspaces/${wsId}/candidates`, { params }).then((r) => r.data);
}

export async function getCandidate(wsId: number, id: number) {
  return client.get(`/workspaces/${wsId}/candidates/${id}`).then((r) => r.data);
}

export async function overrideField(wsId: number, id: number, body: unknown) {
  return client.post(`/workspaces/${wsId}/candidates/${id}/fields`, body).then((r) => r.data);
}

export async function softDelete(wsId: number, id: number) {
  return client.delete(`/workspaces/${wsId}/candidates/${id}`).then((r) => r.data);
}

export async function restoreCandidate(wsId: number, id: number) {
  return client.post(`/workspaces/${wsId}/candidates/${id}/restore`).then((r) => r.data);
}

export async function purgeCandidate(wsId: number, id: number) {
  return client.post(`/workspaces/${wsId}/candidates/${id}/purge`).then((r) => r.data);
}

export async function getTimeline(wsId: number, id: number) {
  return client.get(`/workspaces/${wsId}/candidates/${id}/timeline`).then((r) => r.data);
}

export async function addNote(wsId: number, id: number, content: string) {
  return client.post(`/workspaces/${wsId}/candidates/${id}/notes`, { content }).then((r) => r.data);
}

export async function mergeCandidates(wsId: number, id: number, duplicateId: number, baseRevisionId: number) {
  return client.post(`/workspaces/${wsId}/candidates/${id}/merge`, { duplicate_id: duplicateId, base_revision_id: baseRevisionId }).then((r) => r.data);
}

export async function candidateAssignments(wsId: number, id: number) {
  return client.get(`/workspaces/${wsId}/candidates/${id}/assignments`).then((r) => r.data);
}
