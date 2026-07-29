import { useEffect, useMemo, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import { RotateCcw } from "lucide-react";
import type { DesignPlan } from "@/types/design";
import { computeRoomLayout } from "@/lib/roomLayout";
import type { LayoutItem } from "@/lib/roomLayout";

function FurnitureBox({
  item,
  onHover,
}: {
  item: LayoutItem;
  onHover: (name: string | null) => void;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <group position={item.position} rotation={[0, item.rotationY, 0]}>
      <mesh
        castShadow
        onPointerOver={(e) => {
          e.stopPropagation();
          setHovered(true);
          onHover(item.name);
        }}
        onPointerOut={() => {
          setHovered(false);
          onHover(null);
        }}
      >
        <boxGeometry args={item.size} />
        <meshStandardMaterial
          color={hovered ? "#8FA47A" : item.color}
          roughness={0.75}
          metalness={0.05}
        />
      </mesh>
      {hovered && (
        <Html center distanceFactor={8} position={[0, item.size[1] / 2 + 0.3, 0]}>
          <div className="whitespace-nowrap rounded-lg bg-stone-800/90 px-2 py-1 text-xs text-white">
            {item.name}
          </div>
        </Html>
      )}
    </group>
  );
}

function Room({ width, depth, height }: { width: number; depth: number; height: number }) {
  return (
    <group>
      {/* 地面 */}
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]} receiveShadow>
        <planeGeometry args={[width, depth]} />
        <meshStandardMaterial color="#E4D3B8" roughness={0.9} />
      </mesh>
      {/* 后墙 */}
      <mesh position={[0, height / 2, -depth / 2]}>
        <planeGeometry args={[width, height]} />
        <meshStandardMaterial color="#F3ECDD" roughness={1} side={2} />
      </mesh>
      {/* 左墙 */}
      <mesh position={[-width / 2, height / 2, 0]} rotation={[0, Math.PI / 2, 0]}>
        <planeGeometry args={[depth, height]} />
        <meshStandardMaterial color="#EDE4D2" roughness={1} side={2} />
      </mesh>
      {/* 网格辅助线 */}
      <gridHelper args={[Math.max(width, depth), Math.max(width, depth) * 2, "#CBBfa6", "#DBCFB6"]} />
    </group>
  );
}

export default function RoomView3D({
  plan,
  roomType,
}: {
  plan: DesignPlan;
  roomType: string;
}) {
  const scene = useMemo(() => computeRoomLayout(plan, roomType), [plan, roomType]);
  const [hoverName, setHoverName] = useState<string | null>(null);

  // Canvas 在 tab 切换动画中挂载时初次测量可能失败，挂载后触发一次 resize 兜底
  useEffect(() => {
    const t = setTimeout(() => window.dispatchEvent(new Event("resize")), 60);
    return () => clearTimeout(t);
  }, []);

  return (
    <div className="relative h-[460px] overflow-hidden rounded-3xl border border-cream-200 bg-gradient-to-b from-[#f2ece0] to-[#e6dcc8]">
      <Canvas
        shadows
        frameloop="demand"
        gl={{ preserveDrawingBuffer: true }}
        camera={{ position: [scene.width * 0.9, scene.height * 1.6, scene.depth * 1.1], fov: 45 }}
      >
        <ambientLight intensity={0.75} />
        <directionalLight
          position={[4, 8, 5]}
          intensity={1.1}
          castShadow
          shadow-mapSize-width={1024}
          shadow-mapSize-height={1024}
        />
        <Room width={scene.width} depth={scene.depth} height={scene.height} />
        {scene.items.map((item) => (
          <FurnitureBox key={item.id} item={item} onHover={setHoverName} />
        ))}
        <OrbitControls
          enablePan={false}
          minDistance={3}
          maxDistance={16}
          maxPolarAngle={Math.PI / 2.1}
          target={[0, 0.5, 0]}
        />
      </Canvas>

      {/* 覆盖信息条 */}
      <div className="pointer-events-none absolute top-3 left-4 rounded-full bg-white/85 px-3 py-1 text-xs font-medium text-stone-600 backdrop-blur">
        {scene.roomType} · {scene.width}m × {scene.depth}m · {scene.items.length} 件家具
      </div>
      <div className="pointer-events-none absolute right-4 bottom-3 flex items-center gap-1.5 rounded-full bg-white/85 px-3 py-1 text-xs text-stone-500 backdrop-blur">
        <RotateCcw className="h-3 w-3" />
        拖动旋转 · 滚轮缩放
      </div>
      {hoverName && (
        <div className="pointer-events-none absolute bottom-3 left-4 rounded-full bg-sage-600 px-3 py-1 text-xs font-medium text-white">
          {hoverName}
        </div>
      )}
    </div>
  );
}
