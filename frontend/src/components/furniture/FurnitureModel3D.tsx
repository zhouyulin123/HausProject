import { RoundedBox } from "@react-three/drei";
import type { Furniture3DSpec } from "@/types/furniture";
import { furnitureModelKind, lampModelKind } from "@/lib/furnitureModelKind";
import { deterministicFurnitureRule } from "@/lib/deterministicFurniture";
import DeterministicFurnitureModel3D from "./DeterministicFurnitureModel3D";

const mm = (value: number) => value / 1000;
const degToRad = (value: number) => (value * Math.PI) / 180;

/** 取尺寸参数数值（数组取第一个）。 */
function dim(spec: Furniture3DSpec, key: string, fallback = 0): number {
  const value = spec.尺寸参数?.[key];
  if (typeof value === "number") return value;
  if (Array.isArray(value) && typeof value[0] === "number") return value[0];
  return fallback;
}

/** 取尺寸参数数组的指定下标（如 适配床垫=[宽,长]）。 */
function dimAt(spec: Furniture3DSpec, key: string, index: number, fallback = 0): number {
  const value = spec.尺寸参数?.[key];
  if (Array.isArray(value) && typeof value[index] === "number") return value[index];
  if (typeof value === "number" && index === 0) return value;
  return fallback;
}

/** 取造型参数数值。 */
function shape(spec: Furniture3DSpec, key: string, fallback = 0): number {
  const value = spec.造型参数?.[key];
  return typeof value === "number" ? value : fallback;
}

/** 取角度（度），可能在结构参数或造型参数里。 */
function angle(spec: Furniture3DSpec, key: string, fallback = 0): number {
  const struct = spec.结构参数 as Record<string, unknown> | undefined;
  const modeling = spec.造型参数 as Record<string, unknown> | undefined;
  const value = struct?.[key] ?? modeling?.[key];
  return typeof value === "number" ? value : fallback;
}

/** 取第一个材质项的主色与 PBR 参数。 */
function primaryMaterial(spec: Furniture3DSpec) {
  const first = spec.材质参数?.[0] ?? {};
  const color = Array.isArray(first.base_color)
    ? (first.base_color[0] ?? "#C3B49A")
    : (first.base_color ?? "#C3B49A");
  return {
    color,
    roughness: typeof first.roughness === "number" ? first.roughness : 0.7,
    metallic: typeof first.metallic === "number" ? first.metallic : 0,
  };
}

function Mat({ spec, color }: { spec: Furniture3DSpec; color?: string }) {
  const material = primaryMaterial(spec);
  return (
    <meshStandardMaterial
      color={color ?? material.color}
      roughness={material.roughness}
      metalness={material.metallic}
    />
  );
}

/** 三人位/单人沙发：底座 + 座垫（分缝）+ 靠背 + 扶手，带圆角与鼓包。 */
function SofaModel({ spec }: { spec: Furniture3DSpec }) {
  const width = mm(dim(spec, "总宽", 2200));
  const depth = mm(dim(spec, "总深", 950));
  const height = mm(dim(spec, "总高", 760));
  const seatH = mm(dim(spec, "座高", 420));
  const seatD = mm(dim(spec, "座深", 610));
  const armW = mm(dim(spec, "扶手宽", 210));
  const armH = mm(dim(spec, "扶手高", 590));
  const groundClearance = mm(dim(spec, "离地", 35));
  const round = mm(shape(spec, "主圆角半径", 60));
  const backLean = degToRad(angle(spec, "靠背后倾角_deg", 9));

  const seatCount = Math.max(1, Math.round(
    typeof spec.结构参数?.座位数 === "number" ? spec.结构参数.座位数 : 3,
  ));
  const innerWidth = Math.max(0.2, width - armW * 2);
  const seatGap = mm(shape(spec, "座包缝隙", 12));
  const seatW = (innerWidth - seatGap * (seatCount - 1)) / seatCount;
  const cushionH = Math.max(0.05, height - seatH);
  const baseH = Math.max(0.05, seatH - groundClearance);
  const backT = mm(150);

  return (
    <group>
      {/* 底座 */}
      <RoundedBox
        args={[width, baseH, depth]}
        radius={round}
        smoothness={4}
        position={[0, groundClearance + baseH / 2, 0]}
      >
        <Mat spec={spec} />
      </RoundedBox>

      {/* 座垫（分缝，鼓包用大圆角） */}
      {Array.from({ length: seatCount }).map((_, index) => (
        <RoundedBox
          key={`seat-${index}`}
          args={[seatW, cushionH, seatD]}
          radius={mm(shape(spec, "座包前缘圆角", 45))}
          smoothness={4}
          position={[
            -innerWidth / 2 + armW + seatW / 2 + index * (seatW + seatGap),
            seatH + cushionH / 2,
            depth / 2 - seatD / 2 - 0.04,
          ]}
        >
          <Mat spec={spec} />
        </RoundedBox>
      ))}

      {/* 靠背（后倾） */}
      <RoundedBox
        args={[innerWidth, height - seatH, backT]}
        radius={round}
        smoothness={4}
        position={[0, seatH + (height - seatH) / 2, -depth / 2 + backT / 2]}
        rotation={[backLean, 0, 0]}
      >
        <Mat spec={spec} />
      </RoundedBox>

      {/* 扶手 ×2 */}
      {[-1, 1].map((side) => (
        <RoundedBox
          key={`arm-${side}`}
          args={[armW, armH, depth]}
          radius={round}
          smoothness={4}
          position={[side * (width - armW) / 2, armH / 2, 0]}
        >
          <Mat spec={spec} />
        </RoundedBox>
      ))}
    </group>
  );
}

/** 茶几/套几：圆角台面 + 四条内收木腿。 */
function CoffeeTableModel({ spec }: { spec: Furniture3DSpec }) {
  const length = mm(dim(spec, "长", dim(spec, "直径", 1100)));
  const width = mm(dim(spec, "宽", dim(spec, "直径", 620)));
  const height = mm(dim(spec, "高", 380));
  const topH = mm(dim(spec, "台面厚", 32));
  const legH = Math.max(0.05, height - topH);
  const legW = mm(28);
  const inset = mm(90);

  return (
    <group>
      <RoundedBox
        args={[length, topH, width]}
        radius={mm(shape(spec, "边缘圆角", 12))}
        smoothness={4}
        position={[0, legH + topH / 2, 0]}
      >
        <Mat spec={spec} />
      </RoundedBox>
      {[
        [-1, -1],
        [1, -1],
        [1, 1],
        [-1, 1],
      ].map(([sx, sz], index) => (
        <RoundedBox
          key={`leg-${index}`}
          args={[legW, legH, legW]}
          radius={mm(4)}
          smoothness={2}
          position={[sx * (length / 2 - inset), legH / 2, sz * (width / 2 - inset)]}
        >
          <Mat spec={spec} />
        </RoundedBox>
      ))}
    </group>
  );
}

/** 床：床架 + 床垫 + 床头。 */
function BedModel({ spec }: { spec: Furniture3DSpec }) {
  const outerW = mm(dim(spec, "外框宽", dim(spec, "外宽", 1960)));
  const outerL = mm(dim(spec, "外框长", dim(spec, "外长", 2120)));
  const bedH = mm(dim(spec, "床面高", 300));
  const headboardH = mm(dim(spec, "床头高", dim(spec, "床头总高", 920)));
  const headboardT = mm(dim(spec, "床头厚", 120));
  const round = mm(shape(spec, "床头圆角", 28));
  const headLean = degToRad(angle(spec, "床头后倾角_deg", 5));

  const mattressW = mm(dimAt(spec, "适配床垫", 0, 1800));
  const mattressL = mm(dimAt(spec, "适配床垫", 1, 2000));
  const mattressH = mm(180);

  return (
    <group>
      {/* 床架 */}
      <RoundedBox
        args={[outerW, bedH, outerL]}
        radius={mm(shape(spec, "边缘圆角", 6))}
        smoothness={4}
        position={[0, bedH / 2, 0]}
      >
        <Mat spec={spec} />
      </RoundedBox>

      {/* 床垫 */}
      <RoundedBox
        args={[mattressW, mattressH, mattressL]}
        radius={mm(30)}
        smoothness={4}
        position={[0, bedH + mattressH / 2, 0]}
      >
        <meshStandardMaterial color="#F1ECE2" roughness={0.92} />
      </RoundedBox>

      {/* 床头（后倾） */}
      <RoundedBox
        args={[outerW, headboardH, headboardT]}
        radius={round}
        smoothness={4}
        position={[0, headboardH / 2, -outerL / 2 + headboardT / 2]}
        rotation={[headLean, 0, 0]}
      >
        <Mat spec={spec} />
      </RoundedBox>
    </group>
  );
}

/** 餐桌：圆形岩板台面 + 锥台底座，或长方形台面 + 四腿。 */
function DiningTableModel({ spec }: { spec: Furniture3DSpec }) {
  const diameter = dim(spec, "直径", 0);
  if (diameter > 0) {
    const radius = mm(diameter / 2);
    const height = mm(dim(spec, "高", 750));
    const topH = mm(dim(spec, "台面厚", 12));
    const baseTopR = mm(dim(spec, "底座上径", 300) / 2);
    const baseBottomR = mm(dim(spec, "底座下径", 680) / 2);
    const baseH = Math.max(0.05, height - topH);
    return (
      <group>
        <mesh position={[0, baseH + topH / 2, 0]}>
          <cylinderGeometry args={[radius, radius, topH, 48]} />
          <Mat spec={spec} />
        </mesh>
        <mesh position={[0, baseH / 2, 0]}>
          <cylinderGeometry args={[baseTopR, baseBottomR, baseH, 32]} />
          <meshStandardMaterial color="#51463D" roughness={0.45} metalness={0.68} />
        </mesh>
      </group>
    );
  }

  const length = mm(dim(spec, "长", 1600));
  const width = mm(dim(spec, "宽", 850));
  const height = mm(dim(spec, "高", 750));
  const topH = mm(dim(spec, "台面厚", 38));
  const legH = Math.max(0.05, height - topH);
  const legW = mm(40);
  const inset = mm(120);

  return (
    <group>
      <RoundedBox
        args={[length, topH, width]}
        radius={mm(shape(spec, "台面圆角", 18))}
        smoothness={4}
        position={[0, legH + topH / 2, 0]}
      >
        <Mat spec={spec} />
      </RoundedBox>
      {[
        [-1, -1],
        [1, -1],
        [1, 1],
        [-1, 1],
      ].map(([sx, sz], index) => (
        <RoundedBox
          key={`leg-${index}`}
          args={[legW, legH, legW]}
          radius={mm(4)}
          smoothness={2}
          position={[sx * (length / 2 - inset), legH / 2, sz * (width / 2 - inset)]}
        >
          <Mat spec={spec} />
        </RoundedBox>
      ))}
    </group>
  );
}

/** 餐椅：座面 + 靠背 + 四腿。 */
function ChairModel({ spec }: { spec: Furniture3DSpec }) {
  const width = mm(dim(spec, "总宽", 460));
  const depth = mm(dim(spec, "总深", 535));
  const height = mm(dim(spec, "总高", 810));
  const seatH = mm(dim(spec, "座高", 455));
  const seatW = mm(dim(spec, "座宽", Math.round(width * 1000)));
  const seatD = mm(dim(spec, "座深", Math.round(depth * 1000)));
  const backH = Math.max(0.1, height - seatH);
  const legW = mm(30);
  const backLean = degToRad(angle(spec, "靠背后倾角_deg", 11));

  return (
    <group>
      {/* 座面 */}
      <RoundedBox
        args={[seatW, mm(40), seatD]}
        radius={mm(shape(spec, "边缘圆角", 5))}
        smoothness={4}
        position={[0, seatH, 0]}
      >
        <Mat spec={spec} />
      </RoundedBox>
      {/* 靠背（后倾） */}
      <RoundedBox
        args={[seatW, backH, mm(40)]}
        radius={mm(shape(spec, "边缘圆角", 5))}
        smoothness={4}
        position={[0, seatH + backH / 2, -depth / 2 + mm(20)]}
        rotation={[backLean, 0, 0]}
      >
        <Mat spec={spec} />
      </RoundedBox>
      {/* 四腿 */}
      {[
        [-1, -1],
        [1, -1],
        [1, 1],
        [-1, 1],
      ].map(([sx, sz], index) => (
        <RoundedBox
          key={`leg-${index}`}
          args={[legW, seatH, legW]}
          radius={mm(3)}
          smoothness={2}
          position={[
            sx * (seatW / 2 - legW / 2 - mm(5)),
            seatH / 2,
            sz * (seatD / 2 - legW / 2 - mm(5)),
          ]}
        >
          <Mat spec={spec} />
        </RoundedBox>
      ))}
    </group>
  );
}

/** 落地灯：底座 + 灯杆 + 半球灯罩。 */
function FloorLampModel({ spec }: { spec: Furniture3DSpec }) {
  const totalH = mm(dim(spec, "总高", 1450));
  const baseD = mm(dim(spec, "底座直径", 280));
  const baseH = mm(dim(spec, "底座高", 25));
  const poleD = mm(dim(spec, "灯杆直径", 22));
  const shadeD = mm(dim(spec, "灯罩直径", 360));
  const shadeH = mm(dim(spec, "灯罩高", 190));
  const poleH = Math.max(0.1, totalH - baseH - shadeH);

  return (
    <group>
      <mesh position={[0, baseH / 2, 0]}>
        <cylinderGeometry args={[baseD / 2, baseD / 2, baseH, 32]} />
        <Mat spec={spec} />
      </mesh>
      <mesh position={[0, baseH + poleH / 2, 0]}>
        <cylinderGeometry args={[poleD / 2, poleD / 2, poleH, 16]} />
        <Mat spec={spec} />
      </mesh>
      <mesh position={[0, totalH - shadeH, 0]}>
        <sphereGeometry args={[shadeD / 2, 32, 16, 0, Math.PI * 2, 0, Math.PI / 2]} />
        <meshStandardMaterial
          color="#F4EEE4"
          roughness={0.4}
          transparent
          opacity={0.9}
        />
      </mesh>
    </group>
  );
}

/** 纸艺吊线床头灯：椭圆纸灯笼 + 吊线。 */
function PendantLampModel({ spec }: { spec: Furniture3DSpec }) {
  const shadeD = mm(dim(spec, "单灯灯罩直径", 300));
  const shadeH = mm(dim(spec, "灯罩高", 250));
  const drop = mm(spec.安装参数?.默认垂吊_mm ?? 600);

  return (
    <group>
      <mesh position={[0, -drop / 2, 0]}>
        <cylinderGeometry args={[mm(2), mm(2), drop, 8]} />
        <meshStandardMaterial color="#E8E0D2" roughness={0.62} />
      </mesh>
      <mesh position={[0, -drop, 0]} scale={[1, shadeH / shadeD, 1]}>
        <sphereGeometry args={[shadeD / 2, 32, 20]} />
        <meshStandardMaterial
          color="#F0E5D2"
          roughness={0.92}
          transparent
          opacity={0.85}
        />
      </mesh>
    </group>
  );
}

/** 黄铜玻璃餐吊灯：环形骨架 + 多个玻璃罩。 */
function RingChandelierModel({ spec }: { spec: Furniture3DSpec }) {
  const bodyD = mm(dim(spec, "灯体直径", 750));
  const ringR = bodyD / 2;
  const tubeR = mm(9);
  const glassD = mm(dim(spec, "玻璃罩直径", 130));
  const shadeCount = 6;
  const drop = mm(spec.安装参数?.默认垂吊_mm ?? 1000);

  return (
    <group position={[0, -drop, 0]}>
      {[-0.45, 0.45].map((x) => (
        <mesh key={x} position={[x * ringR, drop / 2, 0]}>
          <cylinderGeometry args={[mm(2), mm(2), drop, 8]} />
          <meshStandardMaterial color="#A9834F" roughness={0.34} metalness={0.92} />
        </mesh>
      ))}
      <mesh rotation={[Math.PI / 2, 0, 0]}>
        <torusGeometry args={[ringR, tubeR, 16, 64]} />
        <meshStandardMaterial color="#A9834F" roughness={0.34} metalness={0.92} />
      </mesh>
      {Array.from({ length: shadeCount }).map((_, index) => {
        const a = (index / shadeCount) * Math.PI * 2;
        return (
          <mesh key={index} position={[Math.cos(a) * ringR, 0, Math.sin(a) * ringR]}>
            <sphereGeometry args={[glassD / 2, 24, 16]} />
            <meshStandardMaterial
              color="#F1E9DE"
              roughness={0.36}
              transparent
              opacity={0.85}
            />
          </mesh>
        );
      })}
    </group>
  );
}

/** 灯具：按显式安装元数据分发落地灯 / 吊线灯 / 环形吊灯。 */
function LampModel({ spec }: { spec: Furniture3DSpec }) {
  const kind = lampModelKind(spec);
  if (kind === "floor") return <FloorLampModel spec={spec} />;
  if (kind === "pendant") {
    return <PendantLampModel spec={spec} />;
  }
  return <RingChandelierModel spec={spec} />;
}

/** 地毯：薄矩形软片。 */
function RugModel({ spec }: { spec: Furniture3DSpec }) {
  const length = mm(dim(spec, "长", 2400));
  const width = mm(dim(spec, "宽", 1600));
  const thickness = mm(dim(spec, "总厚", 9));
  return (
    <RoundedBox args={[length, thickness, width]} radius={mm(4)} smoothness={2}>
      <Mat spec={spec} />
    </RoundedBox>
  );
}

/** 窗帘：多条竖片模拟自然垂褶。 */
function CurtainModel({ spec }: { spec: Furniture3DSpec }) {
  const width = mm(dim(spec, "单片参考宽", 1800));
  const height = mm(dim(spec, "参考高", 2700));
  const foldCount = 4;
  const foldW = width / foldCount;
  return (
    <group>
      {Array.from({ length: foldCount }).map((_, index) => (
        <RoundedBox
          key={index}
          args={[foldW, height, mm(40)]}
          radius={mm(20)}
          smoothness={3}
          position={[-width / 2 + foldW / 2 + index * foldW, height / 2, 0]}
          rotation={[0, index % 2 === 0 ? 0.06 : -0.06, 0]}
        >
          <Mat spec={spec} />
        </RoundedBox>
      ))}
    </group>
  );
}

/** 床头柜：柜体 + 四条腿。 */
function NightstandModel({ spec }: { spec: Furniture3DSpec }) {
  const width = mm(dim(spec, "宽", 480));
  const depth = mm(dim(spec, "深", 390));
  const height = mm(dim(spec, "高", 520));
  const legH = mm(dim(spec, "腿高", 165));
  const legW = mm(28);
  const bodyH = Math.max(0.1, height - legH);

  return (
    <group>
      <RoundedBox
        args={[width, bodyH, depth]}
        radius={mm(shape(spec, "柜体圆角", 8))}
        smoothness={4}
        position={[0, legH + bodyH / 2, 0]}
      >
        <Mat spec={spec} />
      </RoundedBox>
      {/* 抽屉缝 */}
      <mesh position={[0, legH + bodyH * 0.68, depth / 2 + mm(1)]}>
        <boxGeometry args={[width * 0.88, mm(2), mm(2)]} />
        <meshStandardMaterial color="#7a5c3d" roughness={0.6} />
      </mesh>
      {[
        [-1, -1],
        [1, -1],
        [1, 1],
        [-1, 1],
      ].map(([sx, sz], index) => (
        <RoundedBox
          key={`leg-${index}`}
          args={[legW, legH, legW]}
          radius={mm(3)}
          smoothness={2}
          position={[sx * (width / 2 - legW), legH / 2, sz * (depth / 2 - legW)]}
        >
          <Mat spec={spec} />
        </RoundedBox>
      ))}
    </group>
  );
}

/** 升降书桌：桌板 + 两个升降立柱 + 脚掌。 */
function DeskModel({ spec }: { spec: Furniture3DSpec }) {
  const length = mm(dim(spec, "桌板长", 1600));
  const width = mm(dim(spec, "桌板宽", 750));
  const topH = mm(dim(spec, "桌板厚", 28));
  const height = mm(750);
  const legW = mm(60);
  const footL = mm(dim(spec, "脚掌长", 680));

  return (
    <group>
      <RoundedBox
        args={[length, topH, width]}
        radius={mm(shape(spec, "桌板圆角", 10))}
        smoothness={4}
        position={[0, height - topH / 2, 0]}
      >
        <Mat spec={spec} />
      </RoundedBox>
      {[-1, 1].map((side) => (
        <RoundedBox
          key={`leg-${side}`}
          args={[legW, height - topH, legW]}
          radius={mm(4)}
          smoothness={2}
          position={[side * (length / 2 - legW), (height - topH) / 2, 0]}
        >
          <meshStandardMaterial color="#E4E1DA" roughness={0.5} metalness={0.62} />
        </RoundedBox>
      ))}
      {[-1, 1].map((side) => (
        <RoundedBox
          key={`foot-${side}`}
          args={[footL, mm(20), legW]}
          radius={mm(4)}
          smoothness={2}
          position={[side * (length / 2 - legW), mm(10), 0]}
        >
          <meshStandardMaterial color="#E4E1DA" roughness={0.5} metalness={0.62} />
        </RoundedBox>
      ))}
    </group>
  );
}

/** 人体工学椅：五星脚 + 气杆 + 座垫 + 网背 + 头枕 + 扶手。 */
function OfficeChairModel({ spec }: { spec: Furniture3DSpec }) {
  const seatW = mm(dim(spec, "座宽", 500));
  const seatH = mm(490);
  const backH = mm(600);
  const headrestW = mm(dim(spec, "头枕宽", 310));
  const baseR = mm(320);
  const poleD = mm(50);
  const legW = mm(40);

  return (
    <group>
      {/* 五星脚 */}
      {Array.from({ length: 5 }).map((_, index) => {
        const a = (index / 5) * Math.PI * 2;
        return (
          <RoundedBox
            key={`star-${index}`}
            args={[legW, mm(40), baseR * 0.7]}
            radius={mm(4)}
            smoothness={2}
            position={[Math.cos(a) * baseR * 0.5, mm(20), Math.sin(a) * baseR * 0.5]}
            rotation={[0, -a, 0]}
          >
            <meshStandardMaterial color="#707173" roughness={0.38} metalness={0.88} />
          </RoundedBox>
        );
      })}
      {/* 气杆 */}
      <mesh position={[0, seatH / 2, 0]}>
        <cylinderGeometry args={[poleD / 2, poleD / 2, seatH, 16]} />
        <meshStandardMaterial color="#3A3A3A" roughness={0.5} metalness={0.6} />
      </mesh>
      {/* 座垫 */}
      <RoundedBox
        args={[seatW, mm(60), seatW]}
        radius={mm(15)}
        smoothness={4}
        position={[0, seatH, 0]}
      >
        <Mat spec={spec} />
      </RoundedBox>
      {/* 靠背（后倾） */}
      <RoundedBox
        args={[seatW, backH, mm(50)]}
        radius={mm(20)}
        smoothness={4}
        position={[0, seatH + backH / 2, -seatW / 2 + mm(25)]}
        rotation={[0.1, 0, 0]}
      >
        <Mat spec={spec} />
      </RoundedBox>
      {/* 头枕 */}
      <RoundedBox
        args={[headrestW, mm(120), mm(40)]}
        radius={mm(15)}
        smoothness={4}
        position={[0, seatH + backH + mm(60), -seatW / 2 + mm(20)]}
      >
        <Mat spec={spec} />
      </RoundedBox>
      {/* 扶手 ×2 */}
      {[-1, 1].map((side) => (
        <RoundedBox
          key={`arm-${side}`}
          args={[mm(60), mm(30), mm(240)]}
          radius={mm(8)}
          smoothness={3}
          position={[side * (seatW / 2 + mm(40)), seatH + mm(120), 0]}
        >
          <meshStandardMaterial color="#2B2C2D" roughness={0.58} />
        </RoundedBox>
      ))}
    </group>
  );
}

/** 开放书架：四立柱 + 多层板。 */
function BookshelfModel({ spec }: { spec: Furniture3DSpec }) {
  const width = mm(dim(spec, "宽", 1000));
  const depth = mm(dim(spec, "深", 320));
  const height = mm(dim(spec, "高", 1850));
  const shelfCount = Math.max(2, typeof spec.结构参数?.层数 === "number" ? spec.结构参数.层数 : 5);
  const shelfT = mm(dim(spec, "层板厚", 24));
  const legW = mm(34);
  const gap = (height - shelfT * shelfCount) / (shelfCount - 1);

  return (
    <group>
      {[
        [-1, -1],
        [1, -1],
        [1, 1],
        [-1, 1],
      ].map(([sx, sz], index) => (
        <RoundedBox
          key={`post-${index}`}
          args={[legW, height, legW]}
          radius={mm(4)}
          smoothness={2}
          position={[sx * (width / 2 - legW / 2), height / 2, sz * (depth / 2 - legW / 2)]}
        >
          <Mat spec={spec} />
        </RoundedBox>
      ))}
      {Array.from({ length: shelfCount }).map((_, index) => (
        <RoundedBox
          key={`shelf-${index}`}
          args={[width - legW * 2, shelfT, depth - legW * 2]}
          radius={mm(3)}
          smoothness={2}
          position={[0, shelfT / 2 + index * gap, 0]}
        >
          <Mat spec={spec} />
        </RoundedBox>
      ))}
    </group>
  );
}

/** 程序化 3D 家具模型：按建模参数拼装真实体块，替代方块占位。 */
export default function FurnitureModel3D({ spec }: { spec: Furniture3DSpec }) {
  const deterministicRule = deterministicFurnitureRule(spec);
  if (deterministicRule) {
    return <DeterministicFurnitureModel3D rule={deterministicRule} />;
  }

  const kind = furnitureModelKind(spec.家具类型 ?? "");

  if (kind === "sofa") {
    return <SofaModel spec={spec} />;
  }
  if (kind === "coffeeTable") {
    return <CoffeeTableModel spec={spec} />;
  }
  if (kind === "bed") {
    return <BedModel spec={spec} />;
  }
  if (kind === "diningTable") {
    return <DiningTableModel spec={spec} />;
  }
  if (kind === "officeChair") {
    return <OfficeChairModel spec={spec} />;
  }
  if (kind === "chair") {
    return <ChairModel spec={spec} />;
  }
  if (kind === "lamp") {
    return <LampModel spec={spec} />;
  }
  if (kind === "rug") {
    return <RugModel spec={spec} />;
  }
  if (kind === "curtain") {
    return <CurtainModel spec={spec} />;
  }
  if (kind === "nightstand") {
    return <NightstandModel spec={spec} />;
  }
  if (kind === "desk") {
    return <DeskModel spec={spec} />;
  }
  if (kind === "bookshelf") {
    return <BookshelfModel spec={spec} />;
  }

  // 未支持的类型：退化为带圆角的体块（按总尺寸 + 主材质）
  const width = mm(dim(spec, "总宽", dim(spec, "长", dim(spec, "直径", 800))));
  const height = mm(dim(spec, "总高", dim(spec, "高", 600)));
  const depth = mm(dim(spec, "总深", dim(spec, "宽", 600)));
  const radius = mm(shape(spec, "主圆角半径", 20));
  return (
    <RoundedBox args={[width, height, depth]} radius={radius} smoothness={4}>
      <Mat spec={spec} />
    </RoundedBox>
  );
}
