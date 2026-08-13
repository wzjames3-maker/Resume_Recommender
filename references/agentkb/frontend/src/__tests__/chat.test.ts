import { afterEach, describe, expect, it, vi } from "vitest";

import { streamChat } from "../api/chat";
import { useAuthStore } from "../stores/authStore";

describe("streamChat", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("throws on non-2xx response", async () => {
    useAuthStore.getState().logout();
    global.fetch = vi.fn().mockResolvedValue({ ok: false, status: 500, body: null });
    await expect(
      streamChat({}, { onToken: () => {}, onDone: () => {} })
    ).rejects.toThrow(/500/);
  });

  it("parses token and done events from SSE stream", async () => {
    useAuthStore.getState().logout();
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('data: {"type":"token","content":"hi"}\n\n'));
        controller.enqueue(new TextEncoder().encode('data: {"type":"done","message_id":1}\n\n'));
        controller.close();
      },
    });
    global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, body });
    const tokens: string[] = [];
    let done = false;
    await streamChat({}, { onToken: (t) => tokens.push(t), onDone: () => { done = true; } });
    expect(tokens).toEqual(["hi"]);
    expect(done).toBe(true);
  });
});