import { useAuthStore } from "../stores/authStore";

export async function uploadResumes(wsId: number, files: File[], options: { uploadId: string; sourceChannel: string; templateVersion?: string }) {
  const token = useAuthStore.getState().accessToken;
  const form = new FormData();
  form.append("upload_id", options.uploadId);
  form.append("source_channel", options.sourceChannel);
  if (options.templateVersion) form.append("template_version", options.templateVersion);
  for (const f of files) form.append("files", f);
  const res = await fetch(`/api/v1/workspaces/${wsId}/resumes/upload`, {
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

export async function importResumes(wsId: number, body: unknown) {
  const res = await fetchWithToken(`/api/v1/workspaces/${wsId}/resumes/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function listRuns(wsId: number, params: Record<string, unknown> = {}) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
  const res = await fetchWithToken(`/api/v1/workspaces/${wsId}/resumes/runs${qs ? `?${qs}` : ""}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function getRun(runId: string) {
  const res = await fetchWithToken(`/api/v1/resume-runs/${runId}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function getRunIr(runId: string) {
  const res = await fetchWithToken(`/api/v1/resume-runs/${runId}/ir`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

export async function retryRun(runId: string) {
  const res = await fetchWithToken(`/api/v1/resume-runs/${runId}/retry`, { method: "POST" });
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