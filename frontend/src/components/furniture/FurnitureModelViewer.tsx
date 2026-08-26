import { Canvas } from "@react-three/fiber";
import { ContactShadows, OrbitControls } from "@react-three/drei";
import type { Furniture3DSpec } from "@/types/furniture";
import FurnitureModel3D from "./FurnitureModel3D";
import { deterministicFurnitureRule } from "@/lib/deterministicFurniture";

/** 把尺寸参数取成米制数值（数组取第一个）。 */
function num(value: number | number[] | undefined, fallback: number): number {
  if (typeof value === "number") return value;
  if (Array.isArray(value) && typeof value[0] === "number") return value[0];
  return fallback;
}

/** 按建模尺寸估算家具的包围半径，用于自适应相机距离。 */
function estimateRadius(spec: Furniture3DSpec): number {
  const rule = deterministicFurnitureRule(spec);
  if (rule) {
    const { 宽, 高, 深 } = rule.包围尺寸_mm;
    return Math.max(宽, 高, 深) / 1000 / 2;
  }
  const dims = spec.尺寸参数 ?? {};
  const width = num(dims["总宽"] ?? dims["外框宽"] ?? dims["长"] ?? dims["直径"], 1000);
  const height = num(dims["总高"] ?? dims["高"], 600);
  const depth = num(dims["总深"] ?? dims["宽"], 800);
  return Math.max(width, height, depth) / 1000 / 2;
}

/** 家具 3D 查看器：灯光 + 阴影 + 可旋转缩放的程序化模型。 */
export default function FurnitureModelViewer({
  spec,
}: {
  spec: Furniture3DSpec;
}) {
  const radius = Math.max(0.3, estimateRadius(spec));
  const distance = radius * 3.2 + 0.6;

  return (
    <Canvas
      shadows
      frameloop="demand"
      gl={{ antialias: true }}
      camera={{ position: [distance * 0.75, distance * 0.7, distance], fov: 40 }}
    >
      <color attach="background" args={["#EFE8DB"]} />
      <ambientLight intensity={0.75} />
      <directionalLight
        position={[radius * 3, radius * 4, radius * 2]}
        intensity={1.3}
        castShadow
        shadow-mapSize-width={1024}
        shadow-mapSize-height={1024}
      />
      <group position={[0, 0, 0]}>
        <FurnitureModel3D spec={spec} />
      </group>
      <ContactShadows
        position={[0, 0, 0]}
        opacity={0.35}
        scale={radius * 4}
        blur={2.5}
        far={radius * 2}
      />
      <OrbitControls
        makeDefault
        enablePan={false}
        minDistance={radius * 0.6}
        maxDistance={radius * 6}
        maxPolarAngle={Math.PI / 2}
        target={[0, radius * 0.35, 0]}
      />
    </Canvas>
  );
}
