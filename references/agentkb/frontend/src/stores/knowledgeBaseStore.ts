import { create } from "zustand";
import * as kbApi from "../api/knowledgeBase";

interface KnowledgeBase {
  id: number;
  name: string;
}

interface KnowledgeBaseState {
  items: KnowledgeBase[];
  loading: boolean;
  list: (wsId: number) => Promise<void>;
}

export const useKnowledgeBaseStore = create<KnowledgeBaseState>()((set) => ({
  items: [],
  loading: false,
  list: async (wsId) => {
    set({ loading: true });
    const items = await kbApi.list(wsId);
    set({ items, loading: false });
  },
}));