import { useMemo,useLayoutEffect,Suspense } from "react";
import { Canvas,useThree } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { DoubleSide,Shape,PerspectiveCamera,Vector3 } from "three";
import type { SpatialDocument,SpatialRoom } from "@/types/spatial";
import { spatialBounds } from "@/lib/spatialGeometry";
import { wallPieces } from "@/lib/spatialMeshes";
const palette=["#d4ddd5","#d9d2c4","#cbdbe0","#ddcfd8","#cdd7ba"];
function Frame({ center,radius }: {
  center: [
    number,
    number,
    number
  ];
  radius: number;
}) {
  const { camera,size }=useThree();
  useLayoutEffect(() => {
    if(!(camera instanceof PerspectiveCamera))
      return;
    const vertical=camera.fov*Math.PI/360,horizontal=Math.atan(Math.tan(vertical)*size.width/size.height);
    const distance=radius/Math.sin(Math.min(vertical,horizontal))*1.15;
    camera.position.copy(new Vector3(.8,1,1.1).normalize().multiplyScalar(distance).add(new Vector3(...center)));
    camera.lookAt(...center);
    camera.updateProjectionMatrix();
  },[camera,size.width,size.height,center[0],center[1],center[2],radius]);
  return null;
}
function Floor({ room,color,selected,onSelect }: {
  room: SpatialRoom;
  color: string;
  selected: boolean;
  onSelect: () => void;
}) {
  const shape=useMemo(() => { const s=new Shape(); room.polygon.forEach((p,i) => i? s.lineTo(p.x,-p.z):s.moveTo(p.x,-p.z)); s.closePath(); return s; },[room.polygon]);
  return <mesh rotation={[-Math.PI/2,0,0]} onClick={event => { event.stopPropagation(); onSelect(); }} receiveShadow>
    <shapeGeometry args={[shape]} /><meshStandardMaterial side={DoubleSide} color={selected? "#83b4a0":color} roughness={0.92} />
  </mesh>;
}
export default function SpatialCanvas3D({ document,selected,focus,showWalls,onSelect }: {
  document: SpatialDocument;
  selected: string|null;
  focus: boolean;
  showWalls: boolean;
  onSelect: (id: string) => void;
}) {
  const room=document.rooms.find(r => r.id===selected);
  const bounds=spatialBounds({ ...document, image_reference: null, rooms: focus && room ? [room] : document.rooms });
  const cx=bounds.minX+bounds.width/2,cz=bounds.minZ+bounds.depth/2,size=Math.max(bounds.width,bounds.depth,4);
  const height=Math.max(...document.rooms.map(r => r.height),2.8),cy=showWalls? height/2:0;
  const cameraKey=`${focus? selected:"all"}:${cx.toFixed(2)}:${cz.toFixed(2)}:${size.toFixed(2)}`;
  return <div className="h-full min-h-[420px]" aria-label="整屋三维画布">
    <Canvas key={cameraKey} shadows camera={{ position: [cx+size*.8,size*1.1,cz+size*1.05],fov: 46,near: .01,far: 100000 }} gl={{ preserveDrawingBuffer: true }}>
      <color attach="background" args={["#eef1f2"]} /><ambientLight intensity={1.3} /><directionalLight position={[cx+size,20,cz+size]} intensity={2} castShadow />
      <Suspense fallback={null}>
        {document.rooms.map((r,i) => <Floor key={r.id} room={r} color={palette[i%palette.length]} selected={r.id===selected} onSelect={() => onSelect(r.id)} />)}
        {showWalls&&document.walls.flatMap(w => wallPieces(w,document.openings).map((part,i) => <mesh key={`${w.id}-${i}`} position={[part.x,part.y,part.z]} rotation={[0,part.angle,0]} castShadow receiveShadow onClick={event => { event.stopPropagation(); onSelect(w.room_ids[0]); }}>
          <boxGeometry args={[part.width,part.height,w.thickness]} /><meshStandardMaterial color="#f7f7f3" roughness={.85} />
        </mesh>))}
      </Suspense>
      <gridHelper args={[Math.max(20,size*3),40,"#b3bdb8","#dde3df"]} position={[cx,-.025,cz]} />
      <Frame center={[cx,cy,cz]} radius={Math.hypot(bounds.width,bounds.depth,showWalls? height:0)/2} />
      <OrbitControls makeDefault target={[cx,cy,cz]} maxPolarAngle={Math.PI/2.03} minDistance={.5} maxDistance={size*8} />
    </Canvas>
  </div>;
}
