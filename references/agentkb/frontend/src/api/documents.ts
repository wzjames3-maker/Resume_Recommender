import { useAuthStore } from "../stores/authStore";

export async function uploadDocument(kbId: number, file: File) {
  const token = useAuthStore.getState().accessToken;
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`/api/v1/knowledge-bases/${kbId}/documents`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: form,
  });
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.message ?? `上传失败: HTTP ${res.status}`);
  }
  return res.json();
}

export async function listDocuments(kbId: number, params: Record<string, unknown> = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
  const res = await fetchWithToken(`/api/v1/knowledge-bases/${kbId}/documents${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function getDocument(docId: number) {
  const res = await fetchWithToken(`/api/v1/documents/${docId}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function listChunks(docId: number, params: Record<string, unknown> = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
  const res = await fetchWithToken(`/api/v1/documents/${docId}/chunks${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function deleteDocument(docId: number) {
  const res = await fetchWithToken(`/api/v1/documents/${docId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

export async function retryDocument(docId: number) {
  const res = await fetchWithToken(`/api/v1/documents/${docId}/retry`, { method: "POST" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function fetchWithToken(url: string, init: RequestInit = {}) {
  const token = useAuthStore.getState().accessToken;
  return fetch(url, {
    ...init,
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(init.headers ?? {}) },
  });
}