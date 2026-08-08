import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/tests/**/*.test.ts"],
    // Run all tests in a single worker process to avoid port conflicts
    // on the shared mock backend server.
    singleWorker: true,
  },
});
