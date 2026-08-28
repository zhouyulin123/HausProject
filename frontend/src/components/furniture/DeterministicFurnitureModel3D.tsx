import { useEffect, useMemo } from "react";
import { RoundedBox } from "@react-three/drei";
import {
  CatmullRomCurve3,
  Color,
  DataTexture,
  DoubleSide,
  LinearFilter,
  PlaneGeometry,
  RGBAFormat,
  RedFormat,
  RepeatWrapping,
  Shape,
  ExtrudeGeometry,
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
  const surface = slot.表面类型;
  const isUpholstery = slot.槽位ID === "upholstery" || surface === "fabric" || surface === "rattan";
  const isGlass = surface === "glass";
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
      transparent={isGlass}
      opacity={isGlass ? 0.68 : 1}
      transmission={isGlass ? 0.28 : 0}
      thickness={isGlass ? 0.018 : 0}
      side={surface === "paper" || surface === "fabric" ? DoubleSide : undefined}
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
      const value = Math.round(236 + flowingGrain * 10 + finePores * 5);
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

function structuralSurfaceTexture(part: DeterministicModelPart, size: [number, number, number]) {
  const resolution = 96;
  const data = new Uint8Array(resolution * resolution);
  const mesh = part.几何 === "mesh_panel";
  for (let y = 0; y < resolution; y += 1) {
    for (let x = 0; x < resolution; x += 1) {
      if (mesh) {
        const warp = x % 8 < 2;
        const weft = y % 8 < 2;
        data[y * resolution + x] = warp || weft ? 82 : 205;
      } else {
        const loop = Math.sin(x * 0.72) * 20 + Math.sin(y * 0.58) * 16;
        data[y * resolution + x] = Math.round(184 + loop);
      }
    }
  }
  const texture = new DataTexture(data, resolution, resolution, RedFormat);
  texture.wrapS = RepeatWrapping;
  texture.wrapT = RepeatWrapping;
  texture.magFilter = LinearFilter;
  const period = Math.max(0.006, (part.网格间距_mm ?? 12) / 1000);
  texture.repeat.set(Math.max(2, size[0] / period), Math.max(2, Math.max(size[1], size[2]) / period));
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

function roundedRectangleShape(width: number, depth: number, radius: number) {
  const halfWidth = width / 2;
  const halfDepth = depth / 2;
  const safeRadius = Math.min(radius, halfWidth, halfDepth);
  const shape = new Shape();
  shape.moveTo(-halfWidth + safeRadius, -halfDepth);
  shape.lineTo(halfWidth - safeRadius, -halfDepth);
  shape.quadraticCurveTo(halfWidth, -halfDepth, halfWidth, -halfDepth + safeRadius);
  shape.lineTo(halfWidth, halfDepth - safeRadius);
  shape.quadraticCurveTo(halfWidth, halfDepth, halfWidth - safeRadius, halfDepth);
  shape.lineTo(-halfWidth + safeRadius, halfDepth);
  shape.quadraticCurveTo(-halfWidth, halfDepth, -halfWidth, halfDepth - safeRadius);
  shape.lineTo(-halfWidth, -halfDepth + safeRadius);
  shape.quadraticCurveTo(-halfWidth, -halfDepth, -halfWidth + safeRadius, -halfDepth);
  return shape;
}

function RoundedTabletopPart({
  part,
  material,
  appearance,
}: {
  part: DeterministicModelPart;
  material: DeterministicMaterialSlot;
  appearance: WoodAppearance;
}) {
  const { size, position, rotation } = modelPartTransform(part);
  const geometry = useMemo(() => {
    const planRadius = (part.平面圆角半径_mm ?? 0) / 1000;
    const edgeRadius = Math.min((part.边缘圆角_mm ?? 0) / 1000, size[1] * 0.45);
    const next = new ExtrudeGeometry(
      roundedRectangleShape(size[0], size[2], planRadius),
      {
        depth: Math.max(0.001, size[1] - edgeRadius * 2),
        bevelEnabled: edgeRadius > 0,
        bevelSegments: 3,
        bevelSize: edgeRadius,
        bevelThickness: edgeRadius,
        curveSegments: 8,
        steps: 1,
      },
    );
    next.translate(0, 0, -size[1] / 2 + edgeRadius);
    next.rotateX(-Math.PI / 2);
    next.computeVertexNormals();
    return next;
  }, [part.平面圆角半径_mm, part.边缘圆角_mm, size]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return (
    <mesh geometry={geometry} position={position} rotation={rotation} castShadow receiveShadow>
      <WoodMaterial slot={material} appearance={appearance} size={size} axis="x" />
    </mesh>
  );
}

function cloudTabletopShape(width: number, depth: number) {
  const shape = new Shape();
  shape.moveTo(-width * 0.44, -depth * 0.28);
  shape.bezierCurveTo(-width * 0.58, -depth * 0.05, -width * 0.48, depth * 0.34, -width * 0.2, depth * 0.42);
  shape.bezierCurveTo(width * 0.02, depth * 0.56, width * 0.2, depth * 0.39, width * 0.28, depth * 0.31);
  shape.bezierCurveTo(width * 0.55, depth * 0.31, width * 0.58, -depth * 0.08, width * 0.39, -depth * 0.27);
  shape.bezierCurveTo(width * 0.2, -depth * 0.49, -width * 0.2, -depth * 0.49, -width * 0.44, -depth * 0.28);
  return shape;
}

function CloudTabletopPart({ part, material }: { part: DeterministicModelPart; material: DeterministicMaterialSlot }) {
  const { size, position, rotation } = modelPartTransform(part);
  const geometry = useMemo(() => {
    const bevel = Math.min((part.边缘圆角_mm ?? 8) / 1000, size[1] * 0.42);
    const next = new ExtrudeGeometry(cloudTabletopShape(size[0], size[2]), {
      depth: Math.max(0.001, size[1] - bevel * 2),
      bevelEnabled: bevel > 0,
      bevelSegments: 4,
      bevelSize: bevel,
      bevelThickness: bevel,
      curveSegments: 16,
    });
    next.translate(0, 0, -size[1] / 2 + bevel);
    next.rotateX(-Math.PI / 2);
    next.computeVertexNormals();
    return next;
  }, [part.边缘圆角_mm, size]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return <mesh geometry={geometry} position={position} rotation={rotation} castShadow receiveShadow><PartMaterial slot={material} /></mesh>;
}

function EllipticalTabletopPart({ part, material, wood }: { part: DeterministicModelPart; material: DeterministicMaterialSlot; wood?: WoodAppearance }) {
  const { size, position, rotation } = modelPartTransform(part);
  return (
    <mesh position={position} rotation={rotation} scale={[size[0], size[1], size[2]]} castShadow receiveShadow>
      <cylinderGeometry args={[0.5, 0.5, 1, 64, 1]} />
      {wood && material.表面类型 === "wood"
        ? <WoodMaterial slot={material} appearance={wood} size={size} axis="x" />
        : <PartMaterial slot={material} />}
    </mesh>
  );
}

function RoundPart({ part, material }: { part: DeterministicModelPart; material: DeterministicMaterialSlot }) {
  const { size, position, rotation } = modelPartTransform(part);
  const topRadius = (part.顶部直径_mm ?? part.尺寸_mm[0]) / 2000;
  const bottomRadius = (part.底部直径_mm ?? part.尺寸_mm[0]) / 2000;
  return (
    <mesh position={position} rotation={rotation} castShadow receiveShadow>
      <cylinderGeometry args={[topRadius, bottomRadius, size[1], part.几何 === "frustum" ? 48 : 32, 1]} />
      <PartMaterial slot={material} />
    </mesh>
  );
}

function SpherePart({ part, material }: { part: DeterministicModelPart; material: DeterministicMaterialSlot }) {
  const { size, position, rotation } = modelPartTransform(part);
  return (
    <mesh position={position} rotation={rotation} scale={size} castShadow receiveShadow>
      <sphereGeometry args={[0.5, 32, 24]} />
      <PartMaterial slot={material} />
    </mesh>
  );
}

function TorusPart({ part, material }: { part: DeterministicModelPart; material: DeterministicMaterialSlot }) {
  const { size, position, rotation } = modelPartTransform(part);
  const tubeRadius = Math.max(0.003, size[1] / 2);
  const ringRadius = Math.max(tubeRadius, size[0] / 2 - tubeRadius);
  return (
    <mesh position={position} rotation={[rotation[0] + Math.PI / 2, rotation[1], rotation[2]]} castShadow receiveShadow>
      <torusGeometry args={[ringRadius, tubeRadius, 12, 64]} />
      <PartMaterial slot={material} />
    </mesh>
  );
}

function RoundedGenericPart({ part, material, wood }: { part: DeterministicModelPart; material: DeterministicMaterialSlot; wood?: WoodAppearance }) {
  const { size, position, rotation } = modelPartTransform(part);
  const radius = Math.min((part.圆角_mm ?? 5) / 1000, Math.min(...size) * 0.45);
  return (
    <RoundedBox args={size} radius={Math.max(0.001, radius)} smoothness={4} position={position} rotation={rotation} castShadow receiveShadow>
      {wood && material.表面类型 === "wood"
        ? <WoodMaterial slot={material} appearance={wood} size={size} axis={woodGrainAxis(part)} />
        : <PartMaterial slot={material} />}
    </RoundedBox>
  );
}

function TexturedPanelPart({ part, material }: { part: DeterministicModelPart; material: DeterministicMaterialSlot }) {
  const { size, position, rotation } = modelPartTransform(part);
  const radius = Math.min((part.圆角_mm ?? 5) / 1000, Math.min(...size) * 0.45);
  const texture = useMemo(() => structuralSurfaceTexture(part, size), [part, size]);
  useEffect(() => () => texture.dispose(), [texture]);
  return (
    <RoundedBox args={size} radius={Math.max(0.001, radius)} smoothness={4} position={position} rotation={rotation} castShadow receiveShadow>
      <PartMaterial slot={material} map={texture} bumpMap={texture} bumpScale={part.几何 === "mesh_panel" ? 0.004 : 0.0025} />
    </RoundedBox>
  );
}

function CurtainPart({ part, material }: { part: DeterministicModelPart; material: DeterministicMaterialSlot }) {
  const { size, position, rotation } = modelPartTransform(part);
  const geometry = useMemo(() => {
    const next = new PlaneGeometry(size[0], size[1], 48, 36);
    const vertices = next.attributes.position;
    const period = Math.max(0.04, (part.褶皱周期_mm ?? 110) / 1000);
    for (let index = 0; index < vertices.count; index += 1) {
      const x = vertices.getX(index);
      const y = vertices.getY(index);
      const hem = 0.74 + 0.26 * Math.max(0, 1 - (y + size[1] / 2) / Math.max(size[1], 0.001));
      vertices.setZ(index, Math.sin(x / period * Math.PI * 2) * size[2] * 0.42 * hem);
    }
    vertices.needsUpdate = true;
    next.computeVertexNormals();
    return next;
  }, [part.褶皱周期_mm, size]);
  useEffect(() => () => geometry.dispose(), [geometry]);
  return <mesh geometry={geometry} position={position} rotation={rotation} castShadow receiveShadow><PartMaterial slot={material} /></mesh>;
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
  appearance?: UpholsteryAppearance;
  wood?: WoodAppearance;
}) {
  if (
    part.几何 === "tapered_wood_leg"
    || part.几何 === "top_pivot_tapered_wood_leg"
    || part.几何 === "tapered_wood_post"
  ) {
    return wood
      ? <TaperedWoodPart part={part} material={material} appearance={wood} />
      : <RoundedGenericPart part={part} material={material} />;
  }
  if (part.几何 === "rounded_tabletop") {
    return wood && material.表面类型 === "wood"
      ? <RoundedTabletopPart part={part} material={material} appearance={wood} />
      : <RoundedGenericPart part={part} material={material} />;
  }
  if (part.几何 === "cloud_tabletop") {
    return <CloudTabletopPart part={part} material={material} />;
  }
  if (part.几何 === "elliptical_tabletop") {
    return <EllipticalTabletopPart part={part} material={material} wood={wood} />;
  }
  if (part.几何 === "cylinder" || part.几何 === "frustum" || part.几何 === "tube") {
    return <RoundPart part={part} material={material} />;
  }
  if (part.几何 === "sphere") {
    return <SpherePart part={part} material={material} />;
  }
  if (part.几何 === "torus") {
    return <TorusPart part={part} material={material} />;
  }
  if (part.几何 === "curtain_panel") {
    return <CurtainPart part={part} material={material} />;
  }
  if (part.几何 === "rug_panel" || part.几何 === "mesh_panel") {
    return <TexturedPanelPart part={part} material={material} />;
  }
  if (part.几何 === "rounded_box") {
    return <RoundedGenericPart part={part} material={material} wood={wood} />;
  }

  const isCushion = part.几何 === "rounded_cushion" || part.几何 === "curved_cushion";
  if (isCushion) {
    if (!appearance) return null;
    return <CushionPart part={part} material={material} appearance={appearance} />;
  }
  return wood
    ? <WoodRailPart part={part} material={material} appearance={wood} />
    : <RoundedGenericPart part={part} material={material} />;
}

export default function DeterministicFurnitureModel3D({
  rule,
}: {
  rule: DeterministicFurnitureRule;
}) {
  const materials = new Map(rule.材质槽.map((slot) => [slot.槽位ID, slot]));
  const appearance = rule.外观规则.软包 ? upholsteryAppearance(rule) : undefined;
  const wood = rule.外观规则.木材 ? woodAppearance(rule) : undefined;
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
