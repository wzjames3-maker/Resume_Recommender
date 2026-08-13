import { client } from "./client";

export async function createConversation(kbId: number, title?: string) {
  return client.post("/conversations", { knowledge_base_id: kbId, title }).then((r) => r.data);
}

export async function listConversations(kbId: number, page = 1, pageSize = 20) {
  return client
    .get("/conversations", { params: { knowledge_base_id: kbId, page, page_size: pageSize } })
    .then((r) => r.data);
}

export async function listMessages(convId: number, page = 1, pageSize = 100) {
  return client
    .get(`/conversations/${convId}/messages`, { params: { page, page_size: pageSize } })
    .then((r) => r.data);
}

export async function deleteConversation(convId: number) {
  return client.delete(`/conversations/${convId}`).then((r) => r.data);
}