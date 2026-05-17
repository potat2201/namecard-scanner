import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const lanExpose = process.env.LAN_EXPOSE === "true";

export default defineConfig({
  plugins: [react()],
  server: {
    host: lanExpose ? "0.0.0.0" : true,
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
