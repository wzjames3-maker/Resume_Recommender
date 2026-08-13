import { client } from "./client";

export async function scheduleRound(wsId: number, assignmentId: number, body: unknown) {
  return client.post(`/workspaces/${wsId}/assignments/${assignmentId}/interview-rounds`, body).then((r) => r.data);
}

export async function submitFeedback(wsId: number, roundId: number, body: unknown) {
  return client.post(`/workspaces/${wsId}/interview-rounds/${roundId}/feedback`, body).then((r) => r.data);
}

export async function summarizeRound(wsId: number, roundId: number) {
  return client.post(`/workspaces/${wsId}/interview-rounds/${roundId}/summarize`).then((r) => r.data);
}

export async function listRounds(wsId: number, assignmentId: number) {
  return client.get(`/workspaces/${wsId}/assignments/${assignmentId}/interview-rounds`).then((r) => r.data);
}

export async function listOverdue(wsId: number) {
  return client.get(`/workspaces/${wsId}/interviews/overdue`).then((r) => r.data);
}

export async function updateInterviewResult(wsId: number, assignmentId: number, body: unknown) {
  return client.post(`/workspaces/${wsId}/assignments/${assignmentId}/interview-result`, body).then((r) => r.data);
}
