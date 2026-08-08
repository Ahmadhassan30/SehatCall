import { installGoogleOAuthIpv4Lookup } from "./lib/node-network.js";

installGoogleOAuthIpv4Lookup();

const { default: app } = await import("./app.js");
const { auth, authOptions } = await import("./lib/auth.js");
const { logger } = await import("./lib/logger.js");

const rawPort = process.env["PORT"];

if (!rawPort) {
  throw new Error("PORT environment variable is required but was not provided.");
}

const port = Number(rawPort);

if (Number.isNaN(port) || port <= 0) {
  throw new Error(`Invalid PORT value: "${rawPort}"`);
}

// ── Better Auth schema migration ───────────────────────────────────────────────
// Creates (or idempotently updates) the user / session / account / verification
// tables in data/auth.db on every startup. Safe to run repeatedly.
if (auth && authOptions) {
  try {
    const { getMigrations } = await import("better-auth/db/migration");
    const { runMigrations } = await getMigrations(authOptions);
    await runMigrations();
    logger.info("[auth] Database schema up to date.");
  } catch (err) {
    // Fail fast: starting with auth mounted but no schema means every request
    // dies deep inside Better Auth with an opaque "no such table" error.
    // Better to refuse to boot than to serve a silently broken auth service.
    logger.error({ err }, "[auth] Migration failed — refusing to start with a broken auth schema.");
    process.exit(1);
  }
}

app.listen(port, (err) => {
  if (err) {
    logger.error({ err }, "Error listening on port");
    process.exit(1);
  }
  logger.info({ port }, "Server listening");
});
