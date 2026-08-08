/**
 * Better Auth client for the SehatCall Expo app.
 *
 * Uses:
 *   - Google OAuth via the Better Auth server (Express/TypeScript API)
 *   - @better-auth/expo client plugin for cookie storage in SecureStore
 *
 * The session cookie is persisted under the key "dawa_cookie" in
 * expo-secure-store and is automatically included in authenticated
 * API requests via the apiFetch helper (lib/api.ts).
 *
 * Do NOT call Better Auth endpoints (signIn, signOut, getSession) directly
 * against the Python FastAPI backend — those routes live only on the
 * TypeScript API server at /api/auth/*.
 */

import { createAuthClient } from "better-auth/react";
import { expoClient } from "@better-auth/expo/client";
import * as SecureStore from "expo-secure-store";
import { AUTH_BASE_URL } from "./config";

export const authClient = createAuthClient({
  baseURL: AUTH_BASE_URL,
  basePath: "/api/auth",

  plugins: [
    // @better-auth/expo and better-auth resolve to slightly different copies of
    // the BetterFetch generics, so this structurally-valid plugin does not
    // satisfy BetterAuthClientPlugin at the type level. Suppress rather than
    // cast: casting to BetterAuthClientPlugin collapses $Infer.Session to
    // `never` and breaks session typing across every screen.
    // @ts-expect-error -- cross-package BetterFetch generic mismatch (runtime shape is correct)
    expoClient({
      scheme: "sehatcall",
      storagePrefix: "dawa", // cookies stored as "dawa_cookie" in SecureStore
      storage: SecureStore,
    }),
  ],
});

export type AuthSession = typeof authClient.$Infer.Session;
