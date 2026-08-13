import { client } from "./client";

export async function assignCandidate(wsId: number, jobId: number, body: unknown) {
  return client.post(`/workspaces/${wsId}/jobs/${jobId}/assignments`, body).then((r) => r.data);
}

export async function assignBatch(wsId: number, jobId: number, body: unknown) {
  return client.post(`/workspaces/${wsId}/jobs/${jobId}/assignments/batch`, body).then((r) => r.data);
}

export async function jobBoard(wsId: number, jobId: number) {
  return client.get(`/workspaces/${wsId}/jobs/${jobId}/board`).then((r) => r.data);
}

export async function transitionAssignment(wsId: number, id: number, body: unknown) {
  return client.post(`/workspaces/${wsId}/assignments/${id}/transition`, body).then((r) => r.data);
}

export async function hireAssignment(wsId: number, id: number) {
  return client.post(`/workspaces/${wsId}/assignments/${id}/hire`).then((r) => r.data);
}