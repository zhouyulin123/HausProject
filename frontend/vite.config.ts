import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "node:path";
import { chunkGroupForModule } from "./build/chunkGroups";

const backendPort = Number(process.env.HAUS_BACKEND_PORT || "8081");
if (!Number.isInteger(backendPort) || backendPort < 1 || backendPort > 65535) {
  throw new Error("HAUS_BACKEND_PORT 必须是有效端口");
}

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  build: {
    rollupOptions: {
        output: {
          manualChunks: chunkGroupForModule,
          // 避免 Rollup 将 Vite 的预加载辅助模块吸入 3D 手工分包，
          // 否则入口会反向静态依赖整套 Three.js 运行时。
          onlyExplicitManualChunks: true,
        },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 8080,
    // 后端联调：FastAPI 运行在 8081 端口
    proxy: {
      "/api": `http://127.0.0.1:${backendPort}`,
      "/uploads": `http://127.0.0.1:${backendPort}`,
    },
  },
});
