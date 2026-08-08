/**
 * Transparent proxy: forwards /api/* requests to the DAWA Python backend
 * running on localhost:8000.  This allows the caregiver Expo app to reach
 * the Python backend through a single registered artifact URL.
 *
 * Excluded path: GET /api/healthz is handled by the health router, not proxied.
 */

import http from "http";
import https from "https";
import { type RequestHandler } from "express";

const PYTHON_BACKEND = process.env["DAWA_BACKEND_URL"] || "http://localhost:8000";

export const proxyToPython: RequestHandler = (req, res) => {
  const targetUrl = new URL(req.originalUrl, PYTHON_BACKEND);
  const isHttps = targetUrl.protocol === "https:";
  const lib = isHttps ? https : http;

  // Forward headers but override host
  const headers: Record<string, string | string[] | undefined> = {
    ...req.headers,
    host: targetUrl.host,
  };
  // Don't forward transfer-encoding — we'll pipe the body
  delete headers["transfer-encoding"];

  const options: http.RequestOptions = {
    hostname: targetUrl.hostname,
    port: targetUrl.port || (isHttps ? "443" : "80"),
    path: targetUrl.pathname + (targetUrl.search || ""),
    method: req.method,
    headers: headers as http.OutgoingHttpHeaders,
  };

  const proxy = lib.request(options, (proxyRes) => {
    // Forward status + headers
    res.writeHead(proxyRes.statusCode ?? 502, proxyRes.headers);
    proxyRes.pipe(res, { end: true });
  });

  proxy.on("error", (err) => {
    const code = (err as NodeJS.ErrnoException).code;
    if (code === "ECONNREFUSED") {
      res.status(502).json({
        error: "DAWA_BACKEND_UNAVAILABLE",
        detail: "The Python backend is not running. Start the 'DAWA Backend' workflow.",
      });
    } else {
      res.status(502).json({ error: "PROXY_ERROR", detail: err.message });
    }
  });

  // Pipe the request body (for POST/PUT/PATCH)
  req.pipe(proxy, { end: true });
};
