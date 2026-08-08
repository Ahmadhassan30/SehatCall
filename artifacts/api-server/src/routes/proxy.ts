/**
 * Authenticated proxy: forwards /api/* requests to the DAWA Python backend.
 *
 * Security
 * ────────
 * 1. Strips client-supplied X-DAWA-CAREGIVER-ID and X-DAWA-INTERNAL-SECRET
 *    before forwarding — clients must NEVER be trusted to supply these.
 * 2. When res.locals.caregiverId is set (by requireSession), injects fresh
 *    server-authoritative values of both headers.
 * 3. FastAPI validates DAWA_INTERNAL_API_SECRET to confirm requests came
 *    through this authenticated gateway.
 */

import http from "node:http";
import https from "node:https";
import { type RequestHandler } from "express";
import { logger } from "../lib/logger.js";

const DEFAULT_BACKEND =
  process.env["DAWA_BACKEND_URL"] || "http://localhost:8000";
const DEFAULT_SECRET = process.env["DAWA_INTERNAL_API_SECRET"] || "";
const DEFAULT_PROXY_TIMEOUT_MS = Number(
  process.env["DAWA_PROXY_TIMEOUT_MS"] || 40_000
);

function parsedBodyBuffer(req: Parameters<RequestHandler>[0]): Buffer | null {
  if (req.method === "GET" || req.method === "HEAD") return null;
  if (req.body === undefined) return null;
  if (Buffer.isBuffer(req.body)) return req.body;
  if (typeof req.body === "string") return Buffer.from(req.body);
  return Buffer.from(JSON.stringify(req.body));
}

if (!DEFAULT_SECRET) {
  logger.warn(
    "DAWA_INTERNAL_API_SECRET is not set — FastAPI will reject all gateway requests."
  );
}

/**
 * Factory — lets tests inject a custom backend URL and secret without
 * touching process.env or reloading modules.
 */
export function makeProxyToPython(
  backendUrl: string = DEFAULT_BACKEND,
  internalSecret: string = DEFAULT_SECRET
): RequestHandler {
  return (req, res) => {
    const targetUrl = new URL(req.originalUrl, backendUrl);
    const isHttps = targetUrl.protocol === "https:";
    const lib = isHttps ? https : http;

    // ── Spoof-prevention: strip both identity headers from the client ────────
    const headers: Record<string, string | string[] | undefined> = {
      ...req.headers,
      host: targetUrl.host,
    };
    delete headers["transfer-encoding"];
    delete headers["x-dawa-caregiver-id"];   // strip — never trust client
    delete headers["x-dawa-internal-secret"]; // strip — never trust client

    // ── Inject server-authoritative identity (only for authenticated reqs) ───
    const caregiverId = res.locals["caregiverId"] as string | undefined;
    if (caregiverId) {
      headers["x-dawa-caregiver-id"] = caregiverId;
      headers["x-dawa-internal-secret"] = internalSecret;
    }

    const parsedBody = parsedBodyBuffer(req);
    if (parsedBody) {
      headers["content-length"] = String(parsedBody.length);
      headers["content-type"] = headers["content-type"] || "application/json";
    }

    const options: http.RequestOptions = {
      hostname: targetUrl.hostname,
      port: targetUrl.port || (isHttps ? "443" : "80"),
      path: targetUrl.pathname + (targetUrl.search || ""),
      method: req.method,
      headers: headers as http.OutgoingHttpHeaders,
    };

    const proxy = lib.request(options, (proxyRes) => {
      res.writeHead(proxyRes.statusCode ?? 502, proxyRes.headers);
      proxyRes.pipe(res, { end: true });
    });

    proxy.setTimeout(DEFAULT_PROXY_TIMEOUT_MS, () => {
      proxy.destroy(new Error("DAWA backend request timed out."));
    });

    proxy.on("error", (err) => {
      if (res.headersSent) {
        res.end();
        return;
      }
      const code = (err as NodeJS.ErrnoException).code;
      if (code === "ECONNREFUSED") {
        res.status(502).json({
          error: "DAWA_BACKEND_UNAVAILABLE",
          detail: "The Python backend is not running. Start the 'DAWA Backend' workflow.",
        });
      } else if (err.message === "DAWA backend request timed out.") {
        res.status(504).json({
          error: "DAWA_BACKEND_TIMEOUT",
          detail: "The Python backend took too long to respond. Check the backend logs and try again.",
        });
      } else {
        res.status(502).json({ error: "PROXY_ERROR", detail: err.message });
      }
    });

    if (parsedBody) {
      proxy.end(parsedBody);
    } else {
      req.pipe(proxy, { end: true });
    }
  };
}

/** Production singleton — reads backend URL and secret from env at startup. */
export const proxyToPython: RequestHandler = makeProxyToPython();
