/**
 * requireSession — Express middleware that validates a Better Auth session.
 *
 * Behaviour
 * ─────────
 * auth === null (secrets not configured at startup):
 *   → HTTP 503  { error: "AUTH_NOT_CONFIGURED" }
 *   Protected caregiver endpoints NEVER pass through unauthenticated.
 *
 * auth configured, no valid session:
 *   → HTTP 401  { error: "UNAUTHENTICATED" }
 *
 * auth configured, valid session:
 *   → sets res.locals.caregiverId = session.user.id, calls next()
 */

import type { RequestHandler } from "express";
import { auth as defaultAuth } from "../lib/auth.js";
import { fromNodeHeaders } from "better-auth/node";

type AuthInstance = typeof defaultAuth;

export function makeRequireSession(authInstance: AuthInstance): RequestHandler {
  return async function requireSession(req, res, next) {
    // ── Fail closed: secrets not configured ──────────────────────────────────
    if (!authInstance) {
      res.status(503).json({
        error: "AUTH_NOT_CONFIGURED",
        message:
          "P4 auth secrets are not configured. " +
          "Set BETTER_AUTH_SECRET, BETTER_AUTH_URL, GOOGLE_CLIENT_ID, and " +
          "GOOGLE_CLIENT_SECRET in Replit Secrets, then restart the API Server workflow.",
      });
      return;
    }

    // ── Validate session ──────────────────────────────────────────────────────
    try {
      const session = await authInstance.api.getSession({
        headers: fromNodeHeaders(req.headers),
      });

      if (!session?.user?.id) {
        res.status(401).json({
          error: "UNAUTHENTICATED",
          message: "A valid caregiver session is required.",
        });
        return;
      }

      res.locals["caregiverId"] = session.user.id;
      next();
    } catch {
      res.status(401).json({
        error: "UNAUTHENTICATED",
        message: "Session validation failed.",
      });
    }
  };
}

/** Production singleton. */
export const requireSession: RequestHandler = makeRequireSession(defaultAuth);
