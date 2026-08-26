import { RoundedBox } from "@react-three/drei";
import type {
  DeterministicFurnitureRule,
  DeterministicMaterialSlot,
  DeterministicModelPart,
} from "@/lib/deterministicFurniture";
import { modelPartTransform } from "@/lib/deterministicFurniture";

function materialColor(slot: DeterministicMaterialSlot): string {
  if (Array.isArray(slot.base_color)) return slot.base_color[0] ?? "#8A7A68";
  return slot.base_color ?? "#8A7A68";
}

function PartMaterial({ slot }: { slot: DeterministicMaterialSlot }) {
  const isUpholstery = slot.槽位ID === "upholstery";
  return (
    <meshPhysicalMaterial
      color={materialColor(slot)}
      roughness={slot.roughness ?? 0.7}
      metalness={slot.metallic ?? 0}
      sheen={isUpholstery ? (slot.sheen ?? 0.35) : 0}
      sheenColor={isUpholstery ? materialColor(slot) : "#000000"}
      sheenRoughness={0.72}
    />
  );
}

function TaperedWoodPart({
  part,
  material,
}: {
  part: DeterministicModelPart;
  material: DeterministicMaterialSlot;
}) {
  const { size, position, rotation } = modelPartTransform(part);
  return (
    <group position={position} rotation={rotation}>
      <mesh
        castShadow
        receiveShadow
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
}: {
  part: DeterministicModelPart;
  material: DeterministicMaterialSlot;
}) {
  if (part.几何 === "tapered_wood_leg" || part.几何 === "tapered_wood_post") {
    return <TaperedWoodPart part={part} material={material} />;
  }

  const { size, position, rotation } = modelPartTransform(part);
  const isCushion = part.几何 === "rounded_cushion" || part.几何 === "curved_cushion";
  const smallestSide = Math.min(...size);
  const radius = isCushion
    ? Math.min(smallestSide * 0.46, 0.04)
    : Math.min(smallestSide * 0.18, 0.006);

  return (
    <RoundedBox
      args={size}
      radius={radius}
      smoothness={isCushion ? 6 : 3}
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
  return (
    <group name={rule.模型ID}>
      {rule.部件.map((part) => {
        const material = materials.get(part.材质槽);
        if (!material) return null;
        return <RulePart key={part.部件ID} part={part} material={material} />;
      })}
    </group>
  );
}
