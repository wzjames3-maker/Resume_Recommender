import { afterEach, describe, expect, it, vi } from "vitest";

import { searchChat } from "../api/search";
import { useAuthStore } from "../stores/authStore";

describe("searchChat statistics", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("parses statistics event from SSE stream", async () => {
    useAuthStore.getState().logout();
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('data: {"type":"intent","intent":"statistics"}\n\n'));
        controller.enqueue(new TextEncoder().encode('data: {"type":"statistics","statistics":{"count":2,"dimension":"city","distribution":[{"key":"杭州","count":1},{"key":"上海","count":1}]}}\n\n'));
        controller.enqueue(new TextEncoder().encode('data: {"type":"summary","text":"共有 2 位。城市分布：杭州 1、上海 1。"}\n\n'));
        controller.enqueue(new TextEncoder().encode('data: {"type":"done","message_id":1,"conversation_id":9}\n\n'));
        controller.close();
      },
    });
    global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, body });
    const result = await searchChat(1, "有多少 Java 候选人？城市分布？");
    expect(result.intent).toBe("statistics");
    expect(result.statistics?.count).toBe(2);
    expect(result.statistics?.distribution).toEqual([{ key: "杭州", count: 1 }, { key: "上海", count: 1 }]);
    expect(result.summary).toContain("城市分布");
  });
});