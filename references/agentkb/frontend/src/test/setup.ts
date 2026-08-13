const storage = new Map<string, string>();
globalThis.localStorage = {
  getItem: (key) => storage.get(key) ?? null,
  setItem: (key, value) => void storage.set(key, String(value)),
  removeItem: (key) => void storage.delete(key),
  clear: () => storage.clear(),
  key: () => null,
  get length() {
    return storage.size;
  },
} as Storage;