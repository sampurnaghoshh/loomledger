import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { fileURLToPath, URL } from "node:url";

const frontendDir = fileURLToPath(new URL(".", import.meta.url));

export default defineConfig(({ mode }) => {
  // Backend the dev server proxies to. Default: your own uvicorn; set VITE_API_TARGET in .env.local
  // to use a teammate's backend over the LAN (see .env.example).
  const env = loadEnv(mode, frontendDir, "VITE_");
  const target = env.VITE_API_TARGET || "http://localhost:8000";

  return {
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
        "/api": { target, changeOrigin: true },
        "/ws": { target, ws: true, changeOrigin: true },
      },
    },
  };
});
