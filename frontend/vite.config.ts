import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  server: {
    port: 8080,
    // 后端联调：FastAPI 运行在 8081 端口
    proxy: {
      "/api": "http://localhost:8081",
      "/uploads": "http://localhost:8081",
    },
  },
});
