/**
 * Express application factory.
 *
 * createApp(authInstance, authHandler?, router?) builds a fully wired Express
 * app.  The production default export calls createApp with the module-level
 * auth singleton.  Tests call createApp directly with mock auth instances,
 * spy handlers, and custom routers — no module mocking required.
 *
 * Auth mount rules (fail-closed):
 *   authInstance == null  →  /api/auth/* returns 503 AUTH_NOT_CONFIGURED
 *                            /api/dawa/* returns 503 AUTH_NOT_CONFIGURED (via requireSession)
 *   authInstance set      →  /api/auth/* delegates to Better Auth handler
 *                            /api/dawa/* validates session, then proxies
 */

import express, { type Express, type IRouter } from "express";
import cors from "cors";
import pinoHttp from "pino-http";
import { toNodeHandler } from "better-auth/node";
import { auth as defaultAuth } from "./lib/auth.js";
import { logger } from "./lib/logger.js";
import defaultRouter from "./routes/index.js";

type AuthInstance = typeof defaultAuth;
// Better Auth / Node HTTP handler shape (accepts both raw Node and Express req/res)
type AuthHandler = (req: any, res: any) => void;

/**
 * Builds and returns an Express application.
 *
 * @param authInstance  The Better Auth instance, or null if secrets are missing.
 * @param authHandler   Handler for /api/auth/* routes. Defaults to
 *                      toNodeHandler(authInstance) when authInstance is non-null.
 *                      Pass a spy in tests to verify routing without real OAuth.
 * @param router        The /api sub-router. Defaults to the production router.
 */
export function createApp(
  authInstance: AuthInstance,
  authHandler?: AuthHandler,
  router: IRouter = defaultRouter
): Express {
  const app = express();

  // ── Better Auth routes — MUST be mounted before express.json() ────────────
  // The Better Auth handler parses its own bodies.  If express.json() runs
  // first on /api/auth/* the body stream is consumed and Better Auth fails.
  //
  // Express 5 uses the named wildcard "*splat" syntax (not the Express 4 regex
  // form) for catch-all routes.
  if (authInstance) {
    const handler: AuthHandler = authHandler ?? toNodeHandler(authInstance);
    app.all("/api/auth/*splat", handler);
    logger.info("[auth] Better Auth mounted at /api/auth/*splat");
  } else {
    app.all("/api/auth/*splat", (_req, res) => {
      res.status(503).json({
        error: "AUTH_NOT_CONFIGURED",
        message:
          "P4 auth is not active. Set BETTER_AUTH_SECRET, BETTER_AUTH_URL, " +
          "GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in Replit Secrets, " +
          "then restart the API Server workflow.",
      });
    });
  }

  // ── General middleware ─────────────────────────────────────────────────────
  app.use(
    pinoHttp({
      logger,
      serializers: {
        req(req) {
          return { id: req.id, method: req.method, url: req.url?.split("?")[0] };
        },
        res(res) {
          return { statusCode: res.statusCode };
        },
      },
    })
  );
  app.use(cors());
  app.use(express.json());
  app.use(express.urlencoded({ extended: true }));

  // ── Application router (/api/*) ────────────────────────────────────────────
  app.use("/api", router);

  return app;
}

const app = createApp(defaultAuth);
export default app;
