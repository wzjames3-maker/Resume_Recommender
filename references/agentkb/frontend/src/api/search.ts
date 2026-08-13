import { fetchWithRefresh } from "./chat";

export interface SearchCard {
  candidate_id: number;
  name: string | null;
  city: string | null;
  highest_degree: string | null;
  years_experience: number | null;
  expected_position: string | null;
  matched_conditions: string[];
  profile: { level?: string | null; domain?: string | null };
}

export interface SearchResult {
  intent: string;
  cards: SearchCard[];
  summary: string;
  conversationId: number;
  jobCandidates: JobCandidate[];
  statistics?: StatisticsCard;
}

export interface JobCandidate {
  job_id: number;
  name: string;
  city: string | null;
  headcount: number;
  salary_range: string | null;
}

export interface StatisticsCard {
  count: number;
  dimension: string | null;
  distribution: { key: string; count: number }[];
}

export async function searchChat(
  wsId: number,
  message: string,
  conversationId?: number
): Promise<SearchResult> {
  const res = await fetchWithRefresh(`/api/v1/workspaces/${wsId}/search-chat`, {
    method: "POST",
    body: JSON.stringify({ conversation_id: conversationId, message, stream: true }),
  });
  if (!res.ok) throw new Error(`search request failed: HTTP ${res.status}`);
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const result: SearchResult = { intent: "", cards: [], summary: "", conversationId: conversationId ?? 0, jobCandidates: [], statistics: undefined };
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.startsWith("data:")) continue;
      const event = JSON.parse(line.slice(5).trim());
      if (event.type === "intent") result.intent = event.intent;
      if (event.type === "cards") result.cards = event.cards ?? [];
      if (event.type === "job_candidates") result.jobCandidates = event.jobs ?? [];
      if (event.type === "statistics") result.statistics = event.statistics ?? undefined;
      if (event.type === "summary") result.summary = event.text ?? "";
      if (event.type === "done") result.conversationId = event.conversation_id;
      if (event.type === "error") throw new Error(event.message ?? "搜人失败");
    }
  }
  return result;
}