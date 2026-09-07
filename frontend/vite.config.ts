import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite dev server on port 5173 with proxy to FastAPI backend on port 8001
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    allowedHosts: true,
    proxy: {
      "/api": {
        target: "http://localhost:8001",
        changeOrigin: true,
      },
    },
  },
  build: {
    target: "es2015",
    cssCodeSplit: true,
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks: {
          vendor: ["react", "react-dom", "react-router-dom"],
        },
      },
    },
  },
});
