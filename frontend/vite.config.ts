import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      // Real API responses exported from the seeded database (python -m scripts.export_mocks)
      "@mocks": fileURLToPath(new URL("../docs/api-mocks", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    fs: { allow: [".."] },
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
