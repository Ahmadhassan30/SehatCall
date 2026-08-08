/**
 * App-wide constants.
 *
 * EXPO_PUBLIC_API_BASE_URL: set in your .env or Replit Secrets.
 * This must be the TypeScript API server origin (not FastAPI).
 * Example: https://my-api.replit.dev
 *
 * Note: the API base URL can also be set dynamically in the Settings screen
 * (stored in AsyncStorage via DawaContext) for development convenience.
 * The auth client always uses the env-var URL for session management.
 */

export const APP_DISPLAY_NAME = "DAWA Caregiver";

/**
 * Public API base URL used by the Better Auth client.
 * This is the TypeScript API server (Express), not FastAPI.
 */
export const AUTH_BASE_URL: string =
  process.env["EXPO_PUBLIC_API_BASE_URL"] ?? "";
