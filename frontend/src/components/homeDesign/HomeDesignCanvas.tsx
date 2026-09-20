import { useMemo } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls, Bounds } from "@react-three/drei";
import { Shape, DoubleSide } from "three";
import type { SpatialDocument, SpatialRoom } from "@/types/spatial";
import type { HomeDesignDocument } from "@/types/homeDesign";
import { spatialBounds } from "@/lib/spatialGeometry";
import { wallPieces } from "@/lib/spatialMeshes";
import type { HomeAssetEntry } from "@/lib/useHomeAssets";
import HomeAssetModel from "./HomeAssetModel";
import { clearanceBox } from "./homeDesignFields";

export function homeCanvasProfile(objectCount: number) {
  return { shadows: objectCount < 80 };
}
function Plane({
  room,
  color,
  ceiling,
}: {
  room: SpatialRoom;
  color: string;
  ceiling?: boolean;
}) {
  const shape = useMemo(() => {
    const s = new Shape();
    room.polygon.forEach((p, i) =>
      i ? s.lineTo(p.x, -p.z) : s.moveTo(p.x, -p.z),
    );
    s.closePath();
    return s;
  }, [room.polygon]);
  return (
    <mesh
      rotation={[-Math.PI / 2, 0, 0]}
      position={[0, ceiling ? room.height : 0, 0]}
      receiveShadow
    >
      <shapeGeometry args={[shape]} />
      <meshStandardMaterial
        color={color}
        side={DoubleSide}
        transparent={ceiling}
        opacity={ceiling ? 0.35 : 1}
      />
    </mesh>
  );
}
export default function HomeDesignCanvas({
  space,
  document,
  roomId,
  mode,
  selected,
  onSelect,
  showCeiling,
  assets = {},
  onAssetError,
  selectedPoint,
  onSelectPoint,
}: {
  space: SpatialDocument;
  document: HomeDesignDocument;
  roomId: string;
  mode: "2d" | "3d";
  selected: string | null;
  onSelect: (id: string) => void;
  showCeiling: boolean;
  assets?: Record<number, HomeAssetEntry>;
  onAssetError?: (id:number)=>void;
  selectedPoint?: string | null;
  onSelectPoint?: (id:string)=>void;
}) {
  const rooms = space.rooms.filter((r) => !roomId || r.id === roomId);
  const objects = document.objects.filter(
    (o) => !roomId || o.room_id === roomId,
  );
  const walls = space.walls.filter(
    (w) => !roomId || w.room_ids.includes(roomId),
  );
  const points = (document.points ?? []).filter(p => !roomId || p.room_id === roomId);
  const selectedObject = objects.find(o => o.id === selected);
  const profile = homeCanvasProfile(objects.length);
  const reserve = selectedObject ? clearanceBox(selectedObject) : null;
  const bounds = spatialBounds({ ...space, rooms, image_reference: null });
  const floorColor = (id: string) =>
    document.surfaces.find((s) => s.room_id === id && s.kind === "floor")
      ?.material.color ?? "#e4e8e5";
  const wallColor = (id: string, room: string) =>
    document.surfaces.find((s) => s.room_id === room && s.wall_id === id)
      ?.material.color ?? "#dde1e5";
  if (mode === "2d")
    return (
      <svg
        className="hd-plan"
        aria-label="家装二维画布"
        viewBox={`${bounds.minX - 1} ${bounds.minZ - 1} ${bounds.width + 2} ${bounds.depth + 2}`}
      >
        {rooms.map((r) => (
          <g key={r.id}>
            <polygon
              points={r.polygon.map((p) => `${p.x},${p.z}`).join(" ")}
              fill={floorColor(r.id)}
              stroke="#a4adb3"
              strokeWidth=".025"
            />
            <text
              x={r.polygon[0].x + 0.2}
              y={r.polygon[0].z + 0.35}
              fontSize=".2"
              fill="#52636b"
            >
              {r.name}
            </text>
          </g>
        ))}
        {walls.map((w) => (
          <line
            key={w.id}
            x1={w.start.x}
            y1={w.start.z}
            x2={w.end.x}
            y2={w.end.z}
            stroke={wallColor(w.id, roomId || w.room_ids[0])}
            strokeWidth={w.thickness}
          />
        ))}
        {space.openings
          .filter((o) => walls.some((w) => w.id === o.wall_id))
          .map((o) => {
            const w = walls.find((w) => w.id === o.wall_id)!;
            const len = Math.hypot(w.end.x - w.start.x, w.end.z - w.start.z);
            return (
              <line
                key={o.id}
                x1={w.start.x + ((w.end.x - w.start.x) * o.offset) / len}
                y1={w.start.z + ((w.end.z - w.start.z) * o.offset) / len}
                x2={
                  w.start.x +
                  ((w.end.x - w.start.x) * (o.offset + o.width)) / len
                }
                y2={
                  w.start.z +
                  ((w.end.z - w.start.z) * (o.offset + o.width)) / len
                }
                stroke={o.type === "window" ? "#7cbaca" : "#ffffff"}
                strokeWidth={w.thickness + 0.02}
              />
            );
          })}
        {selectedObject && reserve && <g transform={`translate(${selectedObject.position.x} ${selectedObject.position.z}) rotate(${-selectedObject.rotation})`} pointerEvents="none">
          <rect x={reserve.x-reserve.width/2} y={reserve.z-reserve.depth/2} width={reserve.width} height={reserve.depth} fill="#d99b30" fillOpacity={0.14} stroke="#bd7b16" strokeWidth={0.035} strokeDasharray=".12 .08"/>
        </g>}
        {objects.map((o) => (
          <g
            key={o.id}
            transform={`translate(${o.position.x} ${o.position.z}) rotate(${-o.rotation})`}
            role="button"
            tabIndex={0}
            aria-label={`选择${o.name}`}
            onClick={() => onSelect(o.id)}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(o.id);
              }
            }}
          >
            <rect
              x={-o.size.width / 2}
              y={-o.size.depth / 2}
              width={o.size.width}
              height={o.size.depth}
              fill={o.material.color}
              stroke={selected === o.id ? "#12755a" : "#53666b"}
              strokeWidth={selected === o.id ? 0.07 : 0.02}
            />
            <text
              textAnchor="middle"
              y=".06"
              fontSize=".16"
              fill="#18242b"
              paintOrder="stroke"
              stroke="#fff"
              strokeWidth=".02"
            >
              {o.name}
            </text>
          </g>
        ))}
        {points.map(p => <g key={p.id} role="button" tabIndex={0} aria-label={`选择点位${p.name}`} onClick={()=>onSelectPoint?.(p.id)} onKeyDown={e=>{if(e.key==="Enter" || e.key===" "){e.preventDefault();onSelectPoint?.(p.id);}}}>
          <circle cx={p.position.x} cy={p.position.z} r={selectedPoint===p.id?0.14:0.1} fill={p.confirmed?"#257899":"#b77520"} stroke="#fff" strokeWidth={0.035}/>
          <text x={p.position.x+0.15} y={p.position.z} fontSize=".14" fill="#243438" paintOrder="stroke" stroke="#fff" strokeWidth=".025">{p.name}</text>
        </g>)}
      </svg>
    );
  return (
    <div className="hd-3d" aria-label="家装三维画布">
      <Canvas
        shadows={profile.shadows}
        camera={{ position: [10, 12, 12], fov: 45, near: 0.01, far: 100000 }}
      >
        <color attach="background" args={["#edf1f3"]} />
        <ambientLight intensity={1.4} />
        <directionalLight position={[6, 18, 8]} intensity={2} castShadow={profile.shadows} />
        <Bounds fit clip observe margin={1.3}>
          {rooms.map((r) => (
            <Plane key={r.id} room={r} color={floorColor(r.id)} />
          ))}
          {showCeiling &&
            rooms.map((r) => (
              <Plane
                key={`top-${r.id}`}
                room={r}
                ceiling
                color={
                  document.surfaces.find(
                    (s) => s.room_id === r.id && s.kind === "ceiling",
                  )?.material.color ?? "#ffffff"
                }
              />
            ))}
          {walls.flatMap((w) =>
            wallPieces(w, space.openings).map((p, i) => (
              <mesh
                key={`${w.id}-${i}`}
                position={[p.x, p.y, p.z]}
                rotation={[0, p.angle, 0]}
                receiveShadow
              >
                <boxGeometry args={[p.width, p.height, w.thickness]} />
                <meshStandardMaterial
                  color={wallColor(w.id, roomId || w.room_ids[0])}
                  transparent
                  opacity={0.45}
                />
              </mesh>
            )),
          )}
          {objects.map((o) => o.asset_id ? (
            <HomeAssetModel key={o.id} object={o} entry={assets[o.asset_id]} selected={selected===o.id} onSelect={()=>onSelect(o.id)} onError={()=>onAssetError?.(o.asset_id!)}/>
          ) : (
            <mesh
              key={o.id}
              position={[
                o.position.x,
                o.position.y + o.size.height / 2,
                o.position.z,
              ]}
              rotation={[0, (o.rotation * Math.PI) / 180, 0]}
              castShadow={profile.shadows}
              onClick={(e) => {
                e.stopPropagation();
                onSelect(o.id);
              }}
            >
              <boxGeometry args={[o.size.width, o.size.height, o.size.depth]} />
              <meshStandardMaterial
                color={o.material.color}
                emissive={selected === o.id ? "#155b42" : "#000000"}
                emissiveIntensity={0.25}
                roughness={0.7}
              />
            </mesh>
          ))}
          {points.map(p=><mesh key={p.id} position={[p.position.x,p.position.y,p.position.z]} onClick={e=>{e.stopPropagation();onSelectPoint?.(p.id);}}>
            <sphereGeometry args={[selectedPoint===p.id?0.11:0.08,12,8]}/><meshStandardMaterial color={p.confirmed?"#257899":"#b77520"} emissive={selectedPoint===p.id?"#12627b":"#000000"}/>
          </mesh>)}
          {selectedObject && reserve && <group position={[selectedObject.position.x,selectedObject.position.y,selectedObject.position.z]} rotation={[0,selectedObject.rotation*Math.PI/180,0]}>
            <mesh position={[reserve.x,reserve.y,reserve.z]}><boxGeometry args={[reserve.width,reserve.height,reserve.depth]}/><meshBasicMaterial color="#bd7b16" wireframe transparent opacity={0.7}/></mesh>
          </group>}
        </Bounds>
        <OrbitControls makeDefault maxPolarAngle={Math.PI / 2.02} />
      </Canvas>
    </div>
  );
}
