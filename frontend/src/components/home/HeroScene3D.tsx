import { useEffect, useMemo, useState } from "react";
import { Canvas, useThree } from "@react-three/fiber";
import { Html, OrbitControls } from "@react-three/drei";
import {
  AdditiveBlending,
  BufferGeometry,
  DoubleSide,
  Line as ThreeLine,
  LineDashedMaterial,
  Shape,
  Vector3,
} from "three";
import type { SceneDocument, SceneItem } from "@/types/scene";
import type { FurnitureItem } from "@/types/furniture";
import DeterministicFurnitureModel3D from "@/components/furniture/DeterministicFurnitureModel3D";
import { deterministicFurnitureRule } from "@/lib/deterministicFurniture";
import { createSpatialParticles } from "@/lib/spatialMotion";
import {
  FURNITURE_TIPS,
  HERO_DEMO_SCENES,
  heroModelBaseY,
  heroProductMap,
  type HeroSelectPayload,
} from "@/lib/heroSceneData";

const ACCENT = "#d5ff67";

function getRoomBounds(scene: SceneDocument) {
  const xs = scene.room.floorPolygon.map((point) => point.x);
  const zs = scene.room.floorPolygon.map((point) => point.z);
  return {
    width: Math.max(...xs) - Math.min(...xs),
    depth: Math.max(...zs) - Math.min(...zs),
    centerX: (Math.max(...xs) + Math.min(...xs)) / 2,
    centerZ: (Math.max(...zs) + Math.min(...zs)) / 2,
  };
}

function HeroRoom({ scene }: { scene: SceneDocument }) {
  const floorShape = useMemo(() => {
    const shape = new Shape();
    scene.room.floorPolygon.forEach((point, index) => {
      shape[index === 0 ? "moveTo" : "lineTo"](point.x, -point.z);
    });
    shape.closePath();
    return shape;
  }, [scene.room.floorPolygon]);

  return (
    <group>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.006, 0]} receiveShadow>
        <shapeGeometry args={[floorShape]} />
        <meshStandardMaterial color="#1b231c" roughness={0.9} metalness={0.08} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.001, 0]}>
        <shapeGeometry args={[floorShape]} />
        <meshBasicMaterial color="#6f8b62" wireframe transparent opacity={0.15} />
      </mesh>
    </group>
  );
}

function GrowingWall({
  position,
  size,
}: {
  position: [number, number, number];
  size: [number, number, number];
}) {
  return (
    <mesh position={[position[0], size[1] / 2, position[2]]} castShadow receiveShadow>
      <boxGeometry args={size} />
      <meshPhysicalMaterial
        color="#8ca783"
        transparent
        opacity={0.12}
        roughness={0.42}
        metalness={0.08}
        transmission={0.12}
        side={DoubleSide}
      />
    </mesh>
  );
}

function RoomEnvelope({ scene }: { scene: SceneDocument }) {
  const bounds = useMemo(() => getRoomBounds(scene), [scene]);
  const height = Math.min(scene.room.ceilingHeight, 2.8);

  return (
    <group>
      <GrowingWall
        position={[bounds.centerX, 0, bounds.centerZ - bounds.depth / 2]}
        size={[bounds.width, height, 0.045]}
      />
      <GrowingWall
        position={[bounds.centerX - bounds.width / 2, 0, bounds.centerZ]}
        size={[0.045, height, bounds.depth]}
      />
    </group>
  );
}

function ScanField({ scene }: { scene: SceneDocument }) {
  const bounds = useMemo(() => getRoomBounds(scene), [scene]);
  const span = Math.max(bounds.width, bounds.depth) + 1.4;

  return (
    <group>
      <mesh position={[bounds.centerX, 1.4, bounds.centerZ]}>
        <planeGeometry args={[span, 2.8]} />
        <meshBasicMaterial
          color={ACCENT}
          transparent
          opacity={0.035}
          depthWrite={false}
          blending={AdditiveBlending}
          side={DoubleSide}
        />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[bounds.centerX, 0.018, bounds.centerZ]}>
        <planeGeometry args={[span, 0.035]} />
        <meshBasicMaterial color={ACCENT} transparent opacity={0.8} blending={AdditiveBlending} />
      </mesh>
    </group>
  );
}

function SpatialParticles({ scene, offsetX }: { scene: SceneDocument; offsetX: number }) {
  const bounds = useMemo(() => getRoomBounds(scene), [scene]);
  const particleCount = Math.min(280, Math.max(170, Math.round(bounds.width * bounds.depth * 8)));
  const positions = useMemo(
    () =>
      new Float32Array(
        createSpatialParticles(particleCount, scene.room.id.length * 17, {
          width: bounds.width,
          depth: bounds.depth,
          height: Math.min(scene.room.ceilingHeight, 2.8),
          centerX: bounds.centerX,
          centerZ: bounds.centerZ,
          padding: 1.25,
        }),
      ),
    [bounds, particleCount, scene.room.ceilingHeight, scene.room.id.length],
  );

  return (
    <points position={[offsetX, 0, 0]} frustumCulled={false}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" args={[positions, 3]} />
      </bufferGeometry>
      <pointsMaterial
        color={ACCENT}
        size={0.032}
        transparent
        opacity={0.7}
        depthWrite={false}
        blending={AdditiveBlending}
        sizeAttenuation
      />
    </points>
  );
}

function FlowPath({ items }: { items: SceneItem[] }) {
  const geometry = useMemo(() => {
    const points = items.slice(0, 6).map(
      (item) => new Vector3(item.transform.position.x, 0.035, item.transform.position.z),
    );
    return new BufferGeometry().setFromPoints(points);
  }, [items]);
  const material = useMemo(
    () =>
      new LineDashedMaterial({
        color: ACCENT,
        transparent: true,
        opacity: 0.5,
        dashSize: 0.12,
        gapSize: 0.09,
        depthWrite: false,
      }),
    [],
  );
  const line = useMemo(() => new ThreeLine(geometry, material), [geometry, material]);

  useEffect(() => {
    line.computeLineDistances();
    return () => {
      geometry.dispose();
      material.dispose();
    };
  }, [geometry, line, material]);

  if (items.length < 2) return null;
  return <primitive object={line} />;
}

function HeroFurniture({
  item,
  product,
  ceilingHeight,
  selected,
  onSelect,
}: {
  item: SceneItem;
  product: FurnitureItem;
  ceilingHeight: number;
  selected: boolean;
  onSelect: () => void;
}) {
  const [hovered, setHovered] = useState(false);
  const rule = deterministicFurnitureRule(product.modelSpecJson ?? {});
  if (!rule) return null;
  const dimensions = {
    x: rule.包围尺寸_mm.宽 / 1000,
    y: rule.包围尺寸_mm.高 / 1000,
    z: rule.包围尺寸_mm.深 / 1000,
  };
  const finalY = item.transform.position.y + heroModelBaseY(product, ceilingHeight);
  const ceilingAnchored = product.modelSpecJson?.安装参数?.锚点 === "ceiling";
  const hoverLift = hovered || selected ? 0.06 : 0;
  const selectedScale = selected ? 1.035 : 1;

  useEffect(
    () => () => {
      document.body.style.cursor = "";
    },
    [],
  );

  return (
    <group
      position={[item.transform.position.x, finalY + hoverLift, item.transform.position.z]}
      rotation={[item.transform.rotation.x, item.transform.rotation.y, item.transform.rotation.z]}
      scale={[selectedScale, 1, selectedScale]}
    >
      <group
        onClick={(event) => {
          event.stopPropagation();
          onSelect();
        }}
        onPointerOver={(event) => {
          event.stopPropagation();
          setHovered(true);
          document.body.style.cursor = "pointer";
        }}
        onPointerOut={() => {
          setHovered(false);
          document.body.style.cursor = "";
        }}
      >
        <DeterministicFurnitureModel3D rule={rule} />
      </group>
      {(selected || hovered) && (
        <>
          {!ceilingAnchored && (
            <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0.025, 0]}>
              <ringGeometry args={[Math.max(dimensions.x, dimensions.z) * 0.52, Math.max(dimensions.x, dimensions.z) * 0.56, 48]} />
              <meshBasicMaterial color={ACCENT} transparent opacity={selected ? 0.9 : 0.45} blending={AdditiveBlending} />
            </mesh>
          )}
          <Html center distanceFactor={7} position={[0, dimensions.y / 2 + 0.3, 0]}>
            <div className={`whitespace-nowrap border px-2.5 py-1 font-mono text-[9px] tracking-[0.12em] uppercase backdrop-blur ${selected ? "border-[#d5ff67]/50 bg-[#111713]/90 text-[#d5ff67]" : "border-white/20 bg-[#111713]/80 text-white"}`}>{product.name}</div>
          </Html>
        </>
      )}
    </group>
  );
}

function SceneWorld({
  scene,
  offsetX,
  selectedId,
  products,
  onSelect,
}: {
  scene: SceneDocument;
  offsetX: number;
  selectedId: string | null;
  products: Record<string, FurnitureItem | undefined>;
  onSelect: (item: SceneItem, product: FurnitureItem) => void;
}) {
  return (
    <group position={[offsetX, 0, 0]}>
      <HeroRoom scene={scene} />
      <RoomEnvelope scene={scene} />
      <ScanField scene={scene} />
      <FlowPath items={scene.items} />
      {scene.items.map((item) => {
        const product = products[item.instanceId];
        if (!product) return null;
        return (
          <HeroFurniture
            key={`${item.instanceId}-${item.sku}`}
            item={item}
            product={product}
            ceilingHeight={scene.room.ceilingHeight}
            selected={selectedId === item.instanceId}
            onSelect={() => onSelect(item, product)}
          />
        );
      })}
    </group>
  );
}

function ResponsiveScene({
  scene,
  selectedId,
  products,
  onSelect,
}: {
  scene: SceneDocument;
  selectedId: string | null;
  products: Record<string, FurnitureItem | undefined>;
  onSelect: (item: SceneItem, product: FurnitureItem) => void;
}) {
  const { camera, size } = useThree();
  const isCompact = size.width < 640;
  const offsetX = size.width >= 1024 ? 1.35 : 0;
  const cameraScale = isCompact ? 1.45 : size.width < 1024 ? 1.2 : 1;
  const targetY = isCompact ? 0.9 : (scene.camera?.target.y ?? 0.5);

  useEffect(() => {
    const position = scene.camera?.position ?? { x: 5.3, y: 4.2, z: 6.5 };
    camera.position.set(
      position.x * cameraScale,
      position.y * (isCompact ? 1.08 : 1),
      position.z * cameraScale,
    );
    camera.updateProjectionMatrix();
  }, [camera, cameraScale, isCompact, scene.camera?.position]);

  return (
    <>
      <SpatialParticles scene={scene} offsetX={offsetX} />
      <SceneWorld
        key={scene.room.id}
        scene={scene}
        offsetX={offsetX}
        selectedId={selectedId}
        products={products}
        onSelect={onSelect}
      />
      {size.width >= 1024 && (
        <OrbitControls
          camera={camera}
          makeDefault
          enablePan={false}
          enableZoom={false}
          enableDamping={false}
          minDistance={4}
          maxDistance={16}
          maxPolarAngle={Math.PI / 2.05}
          target={[
            scene.camera?.target.x ?? 0,
            targetY,
            scene.camera?.target.z ?? 0,
          ]}
        />
      )}
    </>
  );
}

/** ThreeUI 启发的“AI 空间生长”场景：扫描、墙体生成、家具显现、动线粒子与视差联动。 */
export default function HeroScene3D({
  scene = HERO_DEMO_SCENES.客厅,
  catalog,
  onSelectItem,
}: {
  scene?: SceneDocument;
  catalog: FurnitureItem[];
  onSelectItem?: (payload: HeroSelectPayload) => void;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const products = useMemo(() => heroProductMap(scene, catalog), [catalog, scene]);

  const handleSelect = (item: SceneItem, product: FurnitureItem) => {
    const nextSelected = selectedId === item.instanceId ? null : item.instanceId;
    setSelectedId(nextSelected);
    onSelectItem?.(
      nextSelected
        ? { name: product.name, category: item.category ?? "", tip: FURNITURE_TIPS[item.category ?? ""] ?? "" }
        : null,
    );
  };

  return (
    <Canvas
      shadows
      dpr={[1, 1.25]}
      frameloop="demand"
      gl={{ antialias: true, powerPreference: "high-performance" }}
      camera={{
        position: [scene.camera?.position.x ?? 5.3, scene.camera?.position.y ?? 4.2, scene.camera?.position.z ?? 6.5],
        fov: scene.camera?.fov ?? 45,
      }}
      onPointerMissed={() => {
        setSelectedId(null);
        onSelectItem?.(null);
      }}
    >
      <color attach="background" args={["#0b0f0c"]} />
      <fog attach="fog" args={["#0b0f0c", 8.5, 19]} />
      <ambientLight intensity={0.52} color="#dce7d5" />
      <directionalLight position={[4, 8, 5]} intensity={2.2} color="#fff2d3" castShadow shadow-mapSize-width={512} shadow-mapSize-height={512} />
      <pointLight position={[-4, 2.8, -3]} intensity={18} distance={10} color="#b9dd8d" />
      <pointLight position={[3, 1.2, 4]} intensity={7} distance={8} color="#d8a27f" />
      <gridHelper args={[18, 36, "#52654c", "#263127"]} position={[0, 0.008, 0]} />
      <ResponsiveScene
        scene={scene}
        selectedId={selectedId}
        products={products}
        onSelect={handleSelect}
      />
    </Canvas>
  );
}
