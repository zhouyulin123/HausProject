import { useEffect, useMemo } from "react";
import { RoundedBox } from "@react-three/drei";
import {
  CatmullRomCurve3,
  Color,
  DataTexture,
  LinearFilter,
  RGBAFormat,
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
  woodAppearance,
  woodGrainAxis,
  woodJoineryMarkers,
  type LocalAxis,
  type UpholsteryAppearance,
  type WoodAppearance,
} from "@/lib/deterministicFurniture";

function materialColor(slot: DeterministicMaterialSlot): string {
  if (Array.isArray(slot.base_color)) return slot.base_color[0] ?? "#8A7A68";
  return slot.base_color ?? "#8A7A68";
}

function PartMaterial({
  slot,
  bumpMap,
  bumpScale = 0,
  map,
  clearcoat = 0,
  clearcoatRoughness = 0,
}: {
  slot: DeterministicMaterialSlot;
  bumpMap?: DataTexture;
  bumpScale?: number;
  map?: DataTexture;
  clearcoat?: number;
  clearcoatRoughness?: number;
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
      map={map}
      clearcoat={clearcoat}
      clearcoatRoughness={clearcoatRoughness}
    />
  );
}

function woodTexture(
  appearance: WoodAppearance,
  size: [number, number, number],
  axis: LocalAxis,
) {
  const resolution = 96;
  const data = new Uint8Array(resolution * resolution * 4);
  for (let y = 0; y < resolution; y += 1) {
    for (let x = 0; x < resolution; x += 1) {
      const u = x / resolution;
      const v = y / resolution;
      const flowingGrain = Math.sin(u * Math.PI * 18 + Math.sin(v * Math.PI * 4) * 1.7);
      const finePores = Math.sin(u * Math.PI * 46 + v * Math.PI * 3) * 0.35;
      const value = Math.round(226 + flowingGrain * 20 + finePores * 12);
      const index = (y * resolution + x) * 4;
      data[index] = value;
      data[index + 1] = value;
      data[index + 2] = value;
      data[index + 3] = 255;
    }
  }
  const texture = new DataTexture(data, resolution, resolution, RGBAFormat);
  const axisIndex = { x: 0, y: 1, z: 2 }[axis];
  const length = size[axisIndex];
  const crossSection = Math.min(...size.filter((_, index) => index !== axisIndex));
  texture.wrapS = RepeatWrapping;
  texture.wrapT = RepeatWrapping;
  texture.magFilter = LinearFilter;
  texture.center.set(0.5, 0.5);
  texture.rotation = axis === "x" ? Math.PI / 2 : 0;
  texture.repeat.set(
    Math.max(1, crossSection / appearance.grainPeriod),
    Math.max(1, length / 0.28),
  );
  texture.needsUpdate = true;
  return texture;
}

function WoodMaterial({
  slot,
  appearance,
  size,
  axis,
}: {
  slot: DeterministicMaterialSlot;
  appearance: WoodAppearance;
  size: [number, number, number];
  axis: LocalAxis;
}) {
  const map = useMemo(() => woodTexture(appearance, size, axis), [appearance, axis, size]);
  useEffect(() => () => map.dispose(), [map]);
  return (
    <PartMaterial
      slot={slot}
      map={map}
      bumpMap={map}
      bumpScale={appearance.normalStrength * 0.006}
      clearcoat={appearance.clearcoat}
      clearcoatRoughness={appearance.clearcoatRoughness}
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
  appearance,
}: {
  part: DeterministicModelPart;
  material: DeterministicMaterialSlot;
  appearance: WoodAppearance;
}) {
  const { size, pivot, childCenter, rotation } = taperedPartPivotTransform(part);
  const axis = woodGrainAxis(part);
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
        <WoodMaterial slot={material} appearance={appearance} size={size} axis={axis} />
      </mesh>
    </group>
  );
}

function markerTransform(
  axis: LocalAxis,
  offset: number,
  size: [number, number, number],
  lineWidth: number,
) {
  const markerSize: [number, number, number] = [size[0] * 1.035, size[1] * 1.035, size[2] * 1.035];
  const position: [number, number, number] = [0, 0, 0];
  const axisIndex = { x: 0, y: 1, z: 2 }[axis];
  markerSize[axisIndex] = lineWidth;
  position[axisIndex] = offset;
  return { markerSize, position };
}

function WoodRailPart({
  part,
  material,
  appearance,
}: {
  part: DeterministicModelPart;
  material: DeterministicMaterialSlot;
  appearance: WoodAppearance;
}) {
  const { size, position, rotation } = modelPartTransform(part);
  const radius = Math.min(Math.min(...size) * 0.18, 0.006);
  const axis = woodGrainAxis(part);
  const markers = woodJoineryMarkers(part, appearance);
  return (
    <group position={position} rotation={rotation}>
      <RoundedBox args={size} radius={radius} smoothness={3} castShadow receiveShadow>
        <WoodMaterial slot={material} appearance={appearance} size={size} axis={axis} />
      </RoundedBox>
      {markers.map(({ axis: markerAxis, offset }) => {
        const marker = markerTransform(markerAxis, offset, size, appearance.shoulderLineWidth);
        return (
          <mesh key={`${markerAxis}-${offset}`} position={marker.position} castShadow>
            <boxGeometry args={marker.markerSize} />
            <meshStandardMaterial
              color={upholsteryLineColor(material, 0.58)}
              roughness={0.74}
            />
          </mesh>
        );
      })}
    </group>
  );
}

function RulePart({
  part,
  material,
  appearance,
  wood,
}: {
  part: DeterministicModelPart;
  material: DeterministicMaterialSlot;
  appearance: UpholsteryAppearance;
  wood: WoodAppearance;
}) {
  if (part.几何 === "tapered_wood_leg" || part.几何 === "tapered_wood_post") {
    return <TaperedWoodPart part={part} material={material} appearance={wood} />;
  }

  const isCushion = part.几何 === "rounded_cushion" || part.几何 === "curved_cushion";
  if (isCushion) {
    return <CushionPart part={part} material={material} appearance={appearance} />;
  }
  return <WoodRailPart part={part} material={material} appearance={wood} />;
}

export default function DeterministicFurnitureModel3D({
  rule,
}: {
  rule: DeterministicFurnitureRule;
}) {
  const materials = new Map(rule.材质槽.map((slot) => [slot.槽位ID, slot]));
  const appearance = upholsteryAppearance(rule);
  const wood = woodAppearance(rule);
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
            wood={wood}
          />
        );
      })}
    </group>
  );
}
