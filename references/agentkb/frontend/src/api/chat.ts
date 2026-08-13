import { useAuthStore } from "../stores/authStore";

export async function fetchWithRefresh(url: string, init: RequestInit): Promise<Response> {
  const { accessToken, refreshToken, setTokens, clearAuth } = useAuthStore.getState();
  const doFetch = (token: string | null) =>
    fetch(url, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
  let res = await doFetch(accessToken);
  if (res.status === 401 && refreshToken) {
    const r = await fetch("/api/v1/auth/refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: refreshToken }),
    });
    if (r.ok) {
      const data = await r.json();
      setTokens(data.access_token);
      res = await doFetch(data.access_token);
    } else {
      clearAuth();
    }
  }
  return res;
}

export async function streamChat(
  body: any,
  cb: { onToken: (t: string) => void; onDone: () => void; onError?: (message: string) => void }
) {
  const res = await fetchWithRefresh("/api/v1/chat", {
    method: "POST",
    body: JSON.stringify({ ...body, stream: true }),
  });
  if (!res.ok) throw new Error(`chat request failed: HTTP ${res.status}`);
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data:")) continue;
      const event = JSON.parse(line.slice(5).trim());
      if (event.type === "token") cb.onToken(event.content);
      if (event.type === "done") cb.onDone();
      if (event.type === "error") cb.onError?.(event.message ?? "生成失败");
    }
  }
}