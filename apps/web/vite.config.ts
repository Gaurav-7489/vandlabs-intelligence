import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Upload ceiling shown/enforced in the SPA. Vercel Functions reject request bodies above 4.5 MB, so builds on Vercel
// (VERCEL=1 at build time) default to 4 MB; the API must use the same VAND_MAX_UPLOAD_BYTES (see render.yaml).
const maxUploadMb = process.env.VITE_MAX_UPLOAD_MB ?? (process.env.VERCEL ? "4" : "25");

export default defineConfig({
  define: { __VAND_MAX_UPLOAD_MB__: JSON.stringify(Number(maxUploadMb)) },
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { "/api": { target: process.env.VITE_API_TARGET ?? "http://localhost:8000", changeOrigin: false } } },
  preview: { port: 4173, proxy: { "/api": { target: process.env.VITE_API_TARGET ?? "http://localhost:8000", changeOrigin: false } } },
  build: { sourcemap: false, chunkSizeWarningLimit: 250 },
});
