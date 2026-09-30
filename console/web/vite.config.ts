import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: the Python API runs on 127.0.0.1:$LAU_API_PORT (default 8765, `lau console`); /api is proxied to it.
const apiPort = process.env.LAU_API_PORT ?? "8765";
const webPort = Number(process.env.VITE_PORT ?? 5173);

export default defineConfig({
  plugins: [react()],
  // Separate dependency caches let several dev servers run side by side (one per developer or agent).
  cacheDir: process.env.VITE_CACHE_DIR ?? "node_modules/.vite",
  server: {
    port: webPort,
    strictPort: true,
    proxy: { "/api": { target: `http://127.0.0.1:${apiPort}`, changeOrigin: true } },
  },
  build: { outDir: "dist", sourcemap: true, chunkSizeWarningLimit: 1500 },
});
