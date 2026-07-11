const API_KEY_SESSION_KEY = "monkeyocr.api-key";
const API_KEY_CHANGE_EVENT = "monkeyocr:api-key-change";

function session(): Storage | null {
  return typeof window === "undefined" ? null : window.sessionStorage;
}

export function getApiKey(): string | null {
  const value = session()?.getItem(API_KEY_SESSION_KEY)?.trim();
  return value || null;
}

export function setApiKey(value: string): void {
  const normalized = value.trim();
  if (!normalized) {
    clearApiKey();
    return;
  }
  session()?.setItem(API_KEY_SESSION_KEY, normalized);
  window.dispatchEvent(new Event(API_KEY_CHANGE_EVENT));
}

export function clearApiKey(): void {
  session()?.removeItem(API_KEY_SESSION_KEY);
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(API_KEY_CHANGE_EVENT));
  }
}

export function subscribeApiKey(listener: () => void): () => void {
  if (typeof window === "undefined") {
    return () => undefined;
  }
  window.addEventListener(API_KEY_CHANGE_EVENT, listener);
  return () => window.removeEventListener(API_KEY_CHANGE_EVENT, listener);
}

export function maskApiKey(value: string): string {
  if (value.length <= 10) {
    return `${value.slice(0, 3)}••••`;
  }
  return `${value.slice(0, 6)}••••${value.slice(-4)}`;
}
