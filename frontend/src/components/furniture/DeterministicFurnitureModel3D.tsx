import { useEffect, useMemo } from "react";
import { RoundedBox } from "@react-three/drei";
import {
  CatmullRomCurve3,
  Color,
  DataTexture,
  LinearFilter,
  RedFormat,
  RepeatWrapping,
  Vector3,
} from "three";
import { RoundedBoxGeometry } from "three-stdlib";
import type {
  DeterministicFurnitureRule,
  DeterministicMaterialSlot,
  DeterministicModelPart,
} from "@/lib/deterministicFurniture";
import {
  modelPartTransform,
  cushionVertexPosition,
  taperedPartPivotTransform,
  upholsteryAppearance,
  type UpholsteryAppearance,
} from "@/lib/deterministicFurniture";

function materialColor(slot: DeterministicMaterialSlot): string {
  if (Array.isArray(slot.base_color)) return slot.base_color[0] ?? "#8A7A68";
  return slot.base_color ?? "#8A7A68";
}

function PartMaterial({
  slot,
  bumpMap,
  bumpScale = 0,
}: {
  slot: DeterministicMaterialSlot;
  bumpMap?: DataTexture;
  bumpScale?: number;
}) {
  const isUpholstery = slot.槽位ID === "upholstery";
  return (
    <meshPhysicalMaterial
      color={materialColor(slot)}
      roughness={slot.roughness ?? 0.7}
      metalness={slot.metallic ?? 0}
      sheen={isUpholstery ? (slot.sheen ?? 0.35) : 0}
      sheenColor={isUpholstery ? materialColor(slot) : "#000000"}
      sheenRoughness={0.72}
      bumpMap={bumpMap}
      bumpScale={bumpScale}
    />
  );
}

function fabricTexture(appearance: UpholsteryAppearance, size: [number, number, number]) {
  const resolution = 64;
  const data = new Uint8Array(resolution * resolution);
  for (let y = 0; y < resolution; y += 1) {
    for (let x = 0; x < resolution; x += 1) {
      const warp = Math.sin((x / resolution) * Math.PI * 24) * 24;
      const weft = Math.sin((y / resolution) * Math.PI * 18) * 16;
      const nap = appearance.directionalNap ? (y / resolution - 0.5) * 14 : 0;
      data[y * resolution + x] = Math.round(128 + warp + weft + nap);
    }
  }
  const texture = new DataTexture(data, resolution, resolution, RedFormat);
  texture.wrapS = RepeatWrapping;
  texture.wrapT = RepeatWrapping;
  texture.magFilter = LinearFilter;
  texture.repeat.set(
    Math.max(1, size[0] / appearance.fabricPeriod),
    Math.max(1, Math.max(size[1], size[2]) / appearance.fabricPeriod),
  );
  texture.needsUpdate = true;
  return texture;
}

function upholsteryLineColor(slot: DeterministicMaterialSlot, multiplier: number) {
  return `#${new Color(materialColor(slot)).multiplyScalar(multiplier).getHexString()}`;
}

function cushionOutline(
  geometry: DeterministicModelPart["几何"],
  size: [number, number, number],
  inset: number,
  appearance: UpholsteryAppearance,
) {
  const halfX = size[0] / 2 - inset;
  const halfY = size[1] / 2 - inset;
  const halfZ = size[2] / 2 - inset;
  const corner = Math.min(0.035, halfX * 0.22, Math.max(0.008, halfZ * 0.22));
  const points = geometry === "rounded_cushion"
    ? [
        [-halfX + corner, halfY, halfZ], [halfX - corner, halfY, halfZ],
        [halfX, halfY, halfZ - corner], [halfX, halfY, -halfZ + corner],
        [halfX - corner, halfY, -halfZ], [-halfX + corner, halfY, -halfZ],
        [-halfX, halfY, -halfZ + corner], [-halfX, halfY, halfZ - corner],
      ]
    : [
        [-halfX + corner, halfY, halfZ], [halfX - corner, halfY, halfZ],
        [halfX, halfY - corner, halfZ], [halfX, -halfY + corner, halfZ],
        [halfX - corner, -halfY, halfZ], [-halfX + corner, -halfY, halfZ],
        [-halfX, -halfY + corner, halfZ], [-halfX, halfY - corner, halfZ],
      ];
  return new CatmullRomCurve3(
    points.map(([x, y, z]) => {
      const curved = cushionVertexPosition(geometry, [x, y, z], size, appearance);
      return new Vector3(...curved);
    }),
    true,
    "centripetal",
  );
}

function CushionPart({
  part,
  material,
  appearance,
}: {
  part: DeterministicModelPart;
  material: DeterministicMaterialSlot;
  appearance: UpholsteryAppearance;
}) {
  const { size, position, rotation } = modelPartTransform(part);
  const radius = Math.min(Math.min(...size) * 0.46, 0.04);
  const geometry = useMemo(() => {
    const next = new RoundedBoxGeometry(size[0], size[1], size[2], 8, radius);
    const vertices = next.attributes.position;
    for (let index = 0; index < vertices.count; index += 1) {
      const vertex = cushionVertexPosition(
        part.几何,
        [vertices.getX(index), vertices.getY(index), vertices.getZ(index)],
        size,
        appearance,
      );
      vertices.setXYZ(index, ...vertex);
    }
    vertices.needsUpdate = true;
    next.computeVertexNormals();
    next.computeBoundingBox();
    next.computeBoundingSphere();
    return next;
  }, [appearance, part.几何, radius, size]);
  const bumpMap = useMemo(() => fabricTexture(appearance, size), [appearance, size]);
  const pipingCurve = useMemo(
    () => cushionOutline(part.几何, size, appearance.pipingRadius, appearance),
    [appearance, part.几何, size],
  );
  const seamCurve = useMemo(
    () => cushionOutline(part.几何, size, appearance.seamInset, appearance),
    [appearance, part.几何, size],
  );

  useEffect(() => () => {
    geometry.dispose();
    bumpMap.dispose();
  }, [bumpMap, geometry]);

  return (
    <group position={position} rotation={rotation}>
      <mesh geometry={geometry} castShadow receiveShadow>
        <PartMaterial
          slot={material}
          bumpMap={bumpMap}
          bumpScale={appearance.normalStrength * 0.008}
        />
      </mesh>
      {appearance.pipingEnabled && (
        <mesh castShadow>
          <tubeGeometry args={[pipingCurve, 80, appearance.pipingRadius, 6, true]} />
          <meshStandardMaterial color={upholsteryLineColor(material, 0.82)} roughness={0.78} />
        </mesh>
      )}
      {appearance.seamEnabled && (
        <mesh>
          <tubeGeometry args={[seamCurve, 80, appearance.seamRadius, 4, true]} />
          <meshStandardMaterial color={upholsteryLineColor(material, 0.68)} roughness={0.9} />
        </mesh>
      )}
    </group>
  );
}

function TaperedWoodPart({
  part,
  material,
}: {
  part: DeterministicModelPart;
  material: DeterministicMaterialSlot;
}) {
  const { size, pivot, childCenter, rotation } = taperedPartPivotTransform(part);
  return (
    <group position={pivot} rotation={rotation}>
      <mesh
        castShadow
        receiveShadow
        position={childCenter}
        rotation={[0, Math.PI / 4, 0]}
        scale={[size[0] * Math.SQRT2, size[1], size[2] * Math.SQRT2]}
      >
        <cylinderGeometry args={[0.5, 0.37, 1, 4, 1]} />
        <PartMaterial slot={material} />
      </mesh>
    </group>
  );
}

function RulePart({
  part,
  material,
  appearance,
}: {
  part: DeterministicModelPart;
  material: DeterministicMaterialSlot;
  appearance: UpholsteryAppearance;
}) {
  if (part.几何 === "tapered_wood_leg" || part.几何 === "tapered_wood_post") {
    return <TaperedWoodPart part={part} material={material} />;
  }

  const { size, position, rotation } = modelPartTransform(part);
  const isCushion = part.几何 === "rounded_cushion" || part.几何 === "curved_cushion";
  if (isCushion) {
    return <CushionPart part={part} material={material} appearance={appearance} />;
  }
  const smallestSide = Math.min(...size);
  const radius = Math.min(smallestSide * 0.18, 0.006);

  return (
    <RoundedBox
      args={size}
      radius={radius}
      smoothness={3}
      position={position}
      rotation={rotation}
      castShadow
      receiveShadow
    >
      <PartMaterial slot={material} />
    </RoundedBox>
  );
}

export default function DeterministicFurnitureModel3D({
  rule,
}: {
  rule: DeterministicFurnitureRule;
}) {
  const materials = new Map(rule.材质槽.map((slot) => [slot.槽位ID, slot]));
  const appearance = upholsteryAppearance(rule);
  return (
    <group name={rule.模型ID}>
      {rule.部件.map((part) => {
        const material = materials.get(part.材质槽);
        if (!material) return null;
        return (
          <RulePart
            key={part.部件ID}
            part={part}
            material={material}
            appearance={appearance}
          />
        );
      })}
    </group>
  );
}
