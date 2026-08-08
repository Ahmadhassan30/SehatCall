/**
 * Better Auth server instance.
 *
 * Required secrets (must be set in Replit Secrets to enable P4 auth):
 *   BETTER_AUTH_SECRET   — random string ≥ 32 chars
 *   BETTER_AUTH_URL      — public origin of this TypeScript API server (no trailing slash)
 *   GOOGLE_CLIENT_ID     — from Google Cloud Console OAuth 2.0 credential
 *   GOOGLE_CLIENT_SECRET — same credential
 *
 * If any required secret is missing, auth is disabled at startup (a warning is
 * logged, no crash).  All /api/auth/* routes return 503 until secrets are set.
 * Once secrets are set, restart the API Server workflow to activate auth.
 */

import { betterAuth, type BetterAuthOptions } from "better-auth";
import { expo } from "@better-auth/expo";
import Database from "better-sqlite3";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";
import { logger } from "./logger.js";

// ─── DB path ─────────────────────────────────────────────────────────────────
const __file = fileURLToPath(import.meta.url);
const __dir = path.dirname(__file);
const DATA_DIR =
  process.env["BETTER_AUTH_DB_DIR"] ?? path.resolve(__dir, "../../../data");

type AuthResult = {
  auth: ReturnType<typeof betterAuth>;
  options: BetterAuthOptions;
} | null;

function tryCreateAuth(): AuthResult {
  const secret = process.env["BETTER_AUTH_SECRET"];
  const url = process.env["BETTER_AUTH_URL"];
  const googleClientId = process.env["GOOGLE_CLIENT_ID"];
  const googleClientSecret = process.env["GOOGLE_CLIENT_SECRET"];

  const missing = [
    !secret && "BETTER_AUTH_SECRET",
    !url && "BETTER_AUTH_URL",
    !googleClientId && "GOOGLE_CLIENT_ID",
    !googleClientSecret && "GOOGLE_CLIENT_SECRET",
  ].filter(Boolean);

  if (missing.length > 0) {
    logger.warn(
      { missing },
      "[auth] Auth is DISABLED — required secrets are not set. " +
        "Set them in Replit Secrets and restart the API Server workflow to enable P4 auth."
    );
    return null;
  }

  try {
    fs.mkdirSync(DATA_DIR, { recursive: true });
    const db = new Database(path.join(DATA_DIR, "auth.db"));

    const options: BetterAuthOptions = {
      secret: secret!,
      baseURL: url!,
      basePath: "/api/auth",
      database: db,

      socialProviders: {
        google: {
          clientId: googleClientId!,
          clientSecret: googleClientSecret!,
        },
      },

      trustedOrigins: [
        url!,
        "dawa://",
        "dawa://*",
        // Replit workspace dev domains — the Expo web client originates from the
        // .expo. subdomain; the standard dev domain covers other in-workspace clients.
        ...(process.env["REPLIT_DEV_DOMAIN"]
          ? [
              `https://${process.env["REPLIT_DEV_DOMAIN"]}`,
              // Expo dev domain: same ID with ".expo." inserted before the TLD cluster
              `https://${process.env["REPLIT_DEV_DOMAIN"]!.replace(
                /\.sisko\.replit\.dev$/,
                ".expo.sisko.replit.dev"
              )}`,
            ]
          : []),
        ...(process.env["REPLIT_EXPO_DEV_DOMAIN"]
          ? [`https://${process.env["REPLIT_EXPO_DEV_DOMAIN"]}`]
          : []),
        ...(process.env["NODE_ENV"] === "development"
          ? ["exp://*", "http://localhost:*"]
          : []),
      ],

      plugins: [expo()],
    };

    return { auth: betterAuth(options), options };
  } catch (err) {
    logger.error({ err }, "[auth] Failed to initialise Better Auth.");
    return null;
  }
}

const _result = tryCreateAuth();

/**
 * The Better Auth instance, or null if secrets are not configured.
 * Check for null before calling any auth methods.
 */
export const auth = _result?.auth ?? null;

/**
 * The raw config options passed to betterAuth().
 * Used by index.ts to run schema migrations on startup via getMigrations(authOptions).
 */
export const authOptions = _result?.options ?? null;
