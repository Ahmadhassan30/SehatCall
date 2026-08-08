import { Router, type IRouter, type RequestHandler } from "express";
import healthRouter from "./health.js";
import { proxyToPython } from "./proxy.js";
import { requireSession } from "../middlewares/requireSession.js";

/**
 * Factory — accepts injectable session middleware and proxy handler so tests
 * can wire different auth states and mock backends without module mocking.
 */
export function createRouter(
  sessionMiddleware: RequestHandler,
  proxyMiddleware: RequestHandler = proxyToPython
): IRouter {
  const router: IRouter = Router();

  // /api/healthz — public, no session required
  router.use(healthRouter);

  // /api/dawa/* — ALL caregiver data routes require a valid session.
  // requireSession either returns 503 (no auth), 401 (no session), or calls next().
  // The proxy then strips spoofable identity headers and injects server-authoritative ones.
  router.use("/dawa", sessionMiddleware);

  // Catch-all proxy: forwards every /api/* request to the FastAPI backend.
  router.use(proxyMiddleware);

  return router;
}

export default createRouter(requireSession);
