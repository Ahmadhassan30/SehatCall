/**
 * P4 auth activation tests.
 *
 * Covers:
 *  1. auth missing + /api/dawa/* → 503, never reaches proxy
 *  2. auth missing + /api/auth/* → 503
 *  3. auth configured + no session + /api/dawa/* → 401
 *  4. auth configured + session → reaches proxy
 *  5. Express 5 /api/auth/*splat actually reaches Better Auth handler
 *  6. client-supplied X-DAWA-CAREGIVER-ID is stripped
 *  7. client-supplied X-DAWA-INTERNAL-SECRET is stripped
 *
 * Uses factory functions (createApp / makeRequireSession / makeProxyToPython)
 * so no module mocking or process.env manipulation is required.
 */

import { beforeAll, afterAll, describe, it, expect, vi } from "vitest";
import request from "supertest";
import { createServer, type Server } from "node:http";
import type { AddressInfo } from "node:net";
import type { Express } from "express";

import { createApp } from "../app.js";
import { makeRequireSession } from "../middlewares/requireSession.js";
import { createRouter } from "../routes/index.js";
import { makeProxyToPython } from "../routes/proxy.js";

// ── Mock auth instances ───────────────────────────────────────────────────────

const MOCK_CAREGIVER_ID = "test-caregiver-1";
const MOCK_INTERNAL_SECRET = "test-internal-secret";

const validSession = {
  user: { id: MOCK_CAREGIVER_ID, email: "t@example.com", name: "Test" },
  session: { id: "sess-1", userId: MOCK_CAREGIVER_ID, expiresAt: new Date(Date.now() + 86_400_000) },
};

const mockAuthWithSession = {
  api: { getSession: vi.fn().mockResolvedValue(validSession) },
} as any;

const mockAuthNoSession = {
  api: { getSession: vi.fn().mockResolvedValue(null) },
} as any;

/** Spy used as the Better Auth handler — lets test 5 verify route dispatch. */
const authHandlerSpy = vi.fn((_req: any, res: any) => {
  res.status(200).json({ via: "better-auth" });
});

// ── Mock backend HTTP server (captures incoming headers) ─────────────────────

let mockBackend: Server;
let lastRequestHeaders: Record<string, string | string[] | undefined> = {};

// ── App instances (built once in beforeAll) ───────────────────────────────────

let noAuthApp: Express;     // auth === null
let noSessionApp: Express;  // auth configured, no session
let sessionApp: Express;    // auth configured, valid session → proxy to mock backend

beforeAll(async () => {
  // Start the mock backend on a random port
  mockBackend = createServer((req, res) => {
    lastRequestHeaders = { ...req.headers };
    res.writeHead(200, { "content-type": "application/json" });
    res.end("{}");
  });
  await new Promise<void>((resolve) => mockBackend.listen(0, "127.0.0.1", resolve));
  const backendUrl = `http://127.0.0.1:${(mockBackend.address() as AddressInfo).port}`;

  // auth == null — all protected routes must return 503.
  // The router must also be built with a null-auth session middleware; the
  // module default router is bound to the real auth singleton, which would
  // answer 401 instead of 503 whenever secrets happen to be present in env.
  noAuthApp = createApp(null, undefined, createRouter(makeRequireSession(null)));

  // auth configured, but getSession returns null
  noSessionApp = createApp(
    mockAuthNoSession,
    authHandlerSpy,
    createRouter(makeRequireSession(mockAuthNoSession))
  );

  // auth configured with a valid session — proxy forwards to mock backend
  sessionApp = createApp(
    mockAuthWithSession,
    authHandlerSpy,
    createRouter(
      makeRequireSession(mockAuthWithSession),
      makeProxyToPython(backendUrl, MOCK_INTERNAL_SECRET)
    )
  );
});

afterAll(async () => {
  await new Promise<void>((resolve) => {
    mockBackend.close(() => resolve());
  });
});

// ── 1 + 2: Auth not configured ────────────────────────────────────────────────
describe("auth not configured (auth === null)", () => {
  it("1. GET /api/dawa/patient → 503 AUTH_NOT_CONFIGURED, never reaches proxy", async () => {
    const res = await request(noAuthApp).get("/api/dawa/patient");
    expect(res.status).toBe(503);
    expect(res.body.error).toBe("AUTH_NOT_CONFIGURED");
  });

  it("2. GET /api/auth/session → 503 AUTH_NOT_CONFIGURED", async () => {
    const res = await request(noAuthApp).get("/api/auth/session");
    expect(res.status).toBe(503);
    expect(res.body.error).toBe("AUTH_NOT_CONFIGURED");
  });

  it("2b. POST /api/auth/sign-in/social → 503 (nested path matches *splat)", async () => {
    const res = await request(noAuthApp).post("/api/auth/sign-in/social");
    expect(res.status).toBe(503);
    expect(res.body.error).toBe("AUTH_NOT_CONFIGURED");
  });
});

// ── 3: Auth configured, no session ───────────────────────────────────────────
describe("auth configured, no session", () => {
  it("3. GET /api/dawa/patient → 401 UNAUTHENTICATED", async () => {
    const res = await request(noSessionApp).get("/api/dawa/patient");
    expect(res.status).toBe(401);
    expect(res.body.error).toBe("UNAUTHENTICATED");
  });
});

// ── 4 + 5: Auth configured, valid session ─────────────────────────────────────
describe("auth configured, valid session", () => {
  it("4. GET /api/dawa/patient → reaches proxy (200 from mock backend)", async () => {
    const res = await request(sessionApp).get("/api/dawa/patient");
    expect(res.status).toBe(200);
  });

  it("5. Express 5 /api/auth/*splat → reaches Better Auth handler (named wildcard)", async () => {
    authHandlerSpy.mockClear();
    // GET /api/auth/sign-in/social — nested path must match *splat
    await request(sessionApp).get("/api/auth/sign-in/social");
    expect(authHandlerSpy).toHaveBeenCalled();
  });
});

// ── 6 + 7: Header stripping ───────────────────────────────────────────────────
describe("header stripping (client-supplied identity headers)", () => {
  it("6. client-supplied X-DAWA-CAREGIVER-ID is stripped; session value is injected", async () => {
    lastRequestHeaders = {};
    await request(sessionApp)
      .get("/api/dawa/patient")
      .set("x-dawa-caregiver-id", "evil-override")
      .expect(200);

    // Must NOT forward the spoofed client value
    expect(lastRequestHeaders["x-dawa-caregiver-id"]).not.toBe("evil-override");
    // Must inject the session-derived caregiver ID
    expect(lastRequestHeaders["x-dawa-caregiver-id"]).toBe(MOCK_CAREGIVER_ID);
  });

  it("7. client-supplied X-DAWA-INTERNAL-SECRET is stripped; server secret is injected", async () => {
    lastRequestHeaders = {};
    await request(sessionApp)
      .get("/api/dawa/patient")
      .set("x-dawa-internal-secret", "evil-secret")
      .expect(200);

    // Must NOT forward the spoofed client value
    expect(lastRequestHeaders["x-dawa-internal-secret"]).not.toBe("evil-secret");
    // Must inject the server-authoritative secret
    expect(lastRequestHeaders["x-dawa-internal-secret"]).toBe(MOCK_INTERNAL_SECRET);
  });
});
