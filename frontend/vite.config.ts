import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const lanExpose = process.env.LAN_EXPOSE === "true";
const port = Number(process.env.PORT) || 5173;

export default defineConfig({
  plugins: [react()],
  server: {
    host: lanExpose ? "0.0.0.0" : "localhost",
    port,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  preview: {
    host: lanExpose ? "0.0.0.0" : "localhost",
    port,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
