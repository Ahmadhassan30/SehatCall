/**
 * Authenticated fetch helper for DAWA caregiver API calls.
 *
 * In React Native, cookies do not flow automatically with fetch() the way
 * they do in a browser. The @better-auth/expo client stores the session
 * cookie as a JSON object in SecureStore under the key "dawa_cookie".
 *
 * apiFetch retrieves that cookie, formats it as a Cookie header, and
 * includes it with every request to the TypeScript API server, which
 * then validates the session before proxying to FastAPI.
 */

import * as SecureStore from "expo-secure-store";

/** Must match the storagePrefix used in lib/auth-client.ts */
const COOKIE_STORE_KEY = "dawa_cookie";

/**
 * Read the Better Auth session cookie from SecureStore and format it
 * as a value suitable for the Cookie HTTP request header.
 *
 * Storage format (set by @better-auth/expo client):
 *   { "<cookie-name>": { "value": "...", "expires": "ISO-date" }, ... }
 *
 * We filter out expired entries before building the header value.
 */
async function getAuthCookieHeader(): Promise<string | null> {
  try {
    const stored = await SecureStore.getItemAsync(COOKIE_STORE_KEY);
    if (!stored || stored === "{}") return null;

    const jar = JSON.parse(stored) as Record<
      string,
      { value: string; expires?: string }
    >;
    const now = new Date();
    const parts = Object.entries(jar)
      .filter(([, v]) => !v.expires || new Date(v.expires) > now)
      .map(([name, v]) => `${name}=${v.value}`);

    return parts.length > 0 ? parts.join("; ") : null;
  } catch {
    return null;
  }
}

/**
 * Authenticated fetch.
 *
 * @param baseUrl  The TypeScript API server origin (e.g. "https://my.replit.dev")
 * @param path     Path starting with "/" (e.g. "/api/dawa/patient")
 * @param options  Standard RequestInit options (method, body, headers…)
 */
export async function apiFetch(
  baseUrl: string,
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  if (!baseUrl) {
    throw new Error("Backend URL not configured. Check Settings.");
  }

  const cookie = await getAuthCookieHeader();
  const headers = new Headers(options.headers || {});
  if (cookie) {
    headers.set("Cookie", cookie);
  }

  return fetch(`${baseUrl}${path}`, { ...options, headers });
}
