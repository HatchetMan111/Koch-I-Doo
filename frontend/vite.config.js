import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev-Proxy auf das lokale Backend (Port 8090); im CT liefert das Backend
// die gebaute SPA selbst aus – hier reicht der reine Build.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  server: {
    port: 5195,
    proxy: {
      "/api": "http://127.0.0.1:8090",
      "/images": "http://127.0.0.1:8090",
    },
  },
});
