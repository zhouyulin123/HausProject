import { describe, expect, it } from "vitest";
import { chunkGroupForModule } from "./chunkGroups";

describe("chunkGroupForModule", () => {
  it.each([
    ["/app/node_modules/react-dom/client.js", "vendor-react"],
    ["C:\\app\\node_modules\\react-router-dom\\dist\\index.js", "vendor-react"],
    ["/app/node_modules/three/build/three.module.js", "vendor-three"],
    ["/app/node_modules/@react-three/fiber/dist/index.js", "vendor-react-three"],
    ["/app/node_modules/@react-three/drei/core/OrbitControls.js", "vendor-react-three"],
    ["/app/node_modules/framer-motion/dist/es/index.mjs", "vendor-motion"],
    ["/app/node_modules/lucide-react/dist/esm/lucide-react.js", "vendor-icons"],
  ])("将 %s 分配到 %s", (moduleId, expectedChunk) => {
    expect(chunkGroupForModule(moduleId)).toBe(expectedChunk);
  });

  it("不强行拆分业务代码与未配置的小依赖", () => {
    expect(chunkGroupForModule("/app/src/pages/HomePage.tsx")).toBeUndefined();
    expect(chunkGroupForModule("/app/node_modules/zustand/esm/index.mjs")).toBeUndefined();
  });

  it("按最内层 node_modules 包名分组嵌套依赖", () => {
    expect(
      chunkGroupForModule(
        "/app/node_modules/@react-three/drei/node_modules/three/build/three.module.js",
      ),
    ).toBe("vendor-three");
  });
});
