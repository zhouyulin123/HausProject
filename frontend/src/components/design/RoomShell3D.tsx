import { useEffect, useMemo, useRef } from "react";
import { Html, OrbitControls } from "@react-three/drei";
import { useThree } from "@react-three/fiber";
import { DoubleSide, Path, Shape } from "three";
import {
  buildWallVisuals,
  getRoomBounds,
  getRoomCameraPose,
  type RoomCameraPreset,
  type WallOpeningVisual,
} from "@/lib/roomScene";
import type { SceneDocument } from "@/types/scene";

function OpeningFrame({
  opening,
  ceilingHeight,
}: {
  opening: WallOpeningVisual;
  ceilingHeight: number;
}) {
  const frameThickness = 0.055;
  const frameDepth = 0.045;
  const centerY =
    opening.sillHeight + opening.height / 2 - ceilingHeight / 2;
  const isWindow = opening.type === "window";

  return (
    <group position={[opening.localX, centerY, 0.018]}>
      <mesh position={[-opening.width / 2, 0, 0]} castShadow>
        <boxGeometry
          args={[frameThickness, opening.height + frameThickness, frameDepth]}
        />
        <meshStandardMaterial color="#675f52" roughness={0.72} />
      </mesh>
      <mesh position={[opening.width / 2, 0, 0]} castShadow>
        <boxGeometry
          args={[frameThickness, opening.height + frameThickness, frameDepth]}
        />
        <meshStandardMaterial color="#675f52" roughness={0.72} />
      </mesh>
      <mesh position={[0, opening.height / 2, 0]} castShadow>
        <boxGeometry
          args={[opening.width + frameThickness, frameThickness, frameDepth]}
        />
        <meshStandardMaterial color="#675f52" roughness={0.72} />
      </mesh>
      {(isWindow || opening.sillHeight > 0) && (
        <mesh position={[0, -opening.height / 2, 0]} castShadow>
          <boxGeometry
            args={[opening.width + frameThickness, frameThickness, frameDepth]}
          />
          <meshStandardMaterial color="#675f52" roughness={0.72} />
        </mesh>
      )}
      {isWindow && (
        <mesh position={[0, 0, -0.004]}>
          <planeGeometry
            args={[
              Math.max(0.02, opening.width - frameThickness),
              Math.max(0.02, opening.height - frameThickness),
            ]}
          />
          <meshPhysicalMaterial
            color="#b9d3d4"
            roughness={0.08}
            transmission={0.42}
            transparent
            opacity={0.5}
            depthWrite={false}
          />
        </mesh>
      )}
      <Html
        center
        distanceFactor={9}
        position={[0, opening.height / 2 + 0.16, 0.03]}
      >
        <span className="whitespace-nowrap rounded-full border border-white/70 bg-stone-900/72 px-2 py-0.5 text-[9px] font-medium text-white shadow-sm backdrop-blur">
          {opening.type === "window"
            ? "窗"
            : opening.type === "passage"
              ? "通道"
              : "门"}{" "}
          {opening.width.toFixed(2)} m
        </span>
      </Html>
    </group>
  );
}

function buildWallShape(
  length: number,
  ceilingHeight: number,
  openings: WallOpeningVisual[],
): Shape {
  const shape = new Shape();
  const halfLength = length / 2;
  const halfHeight = ceilingHeight / 2;
  shape.moveTo(-halfLength, -halfHeight);
  shape.lineTo(halfLength, -halfHeight);
  shape.lineTo(halfLength, halfHeight);
  shape.lineTo(-halfLength, halfHeight);
  shape.closePath();

  openings.forEach((opening) => {
    const hole = new Path();
    const left = opening.localX - opening.width / 2;
    const right = opening.localX + opening.width / 2;
    const bottom = opening.sillHeight - halfHeight;
    const top = bottom + opening.height;
    hole.moveTo(left, bottom);
    hole.lineTo(left, top);
    hole.lineTo(right, top);
    hole.lineTo(right, bottom);
    hole.closePath();
    shape.holes.push(hole);
  });

  return shape;
}

export function RoomShell3D({ scene }: { scene: SceneDocument }) {
  const floorShape = useMemo(() => {
    const shape = new Shape();
    scene.room.floorPolygon.forEach((point, index) => {
      const method = index === 0 ? "moveTo" : "lineTo";
      shape[method](point.x, -point.z);
    });
    shape.closePath();
    return shape;
  }, [scene.room.floorPolygon]);
  const walls = useMemo(() => buildWallVisuals(scene), [scene]);
  const wallShapes = useMemo(
    () =>
      Object.fromEntries(
        walls.map((wall) => [
          wall.id,
          buildWallShape(
            wall.length,
            scene.room.ceilingHeight,
            wall.openings,
          ),
        ]),
      ),
    [scene.room.ceilingHeight, walls],
  );
  const bounds = useMemo(() => getRoomBounds(scene), [scene]);
  const gridSize = Math.max(bounds.width, bounds.depth, 1);

  return (
    <group>
      <mesh
        rotation={[-Math.PI / 2, 0, 0]}
        position={[0, -0.012, 0]}
        receiveShadow
      >
        <shapeGeometry args={[floorShape]} />
        <meshStandardMaterial color="#c9b999" roughness={0.9} />
      </mesh>

      {walls.map((wall) => (
        <group
          key={wall.id}
          position={[wall.position.x, wall.position.y, wall.position.z]}
          rotation={[0, wall.rotationY, 0]}
        >
          <mesh receiveShadow>
            <shapeGeometry args={[wallShapes[wall.id]]} />
            <meshStandardMaterial
              color="#eee9dd"
              roughness={0.96}
              side={DoubleSide}
              transparent
              opacity={0.78}
              depthWrite={false}
            />
          </mesh>
          {wall.openings.map((opening) => (
            <OpeningFrame
              key={opening.id}
              opening={opening}
              ceilingHeight={scene.room.ceilingHeight}
            />
          ))}
          <Html
            center
            distanceFactor={10}
            position={[0, -scene.room.ceilingHeight / 2 + 0.09, 0.035]}
          >
            <span className="whitespace-nowrap rounded bg-white/82 px-1.5 py-0.5 font-mono text-[9px] text-stone-600 shadow-sm backdrop-blur">
              {wall.length.toFixed(2)} m
            </span>
          </Html>
        </group>
      ))}

      <gridHelper
        args={[
          Math.ceil(gridSize),
          Math.ceil(gridSize * 10),
          "#796f5f",
          "#b8aa91",
        ]}
        position={[bounds.centerX, 0.006, bounds.centerZ]}
      />
    </group>
  );
}

export function RoomCameraControls({
  scene,
  preset,
}: {
  scene: SceneDocument;
  preset: RoomCameraPreset;
}) {
  const { camera, invalidate } = useThree();
  const controlsRef = useRef<React.ElementRef<typeof OrbitControls>>(null);
  const pose = useMemo(() => getRoomCameraPose(scene, preset), [preset, scene]);
  const bounds = useMemo(() => getRoomBounds(scene), [scene]);

  useEffect(() => {
    camera.position.set(pose.position.x, pose.position.y, pose.position.z);
    camera.up.set(pose.up.x, pose.up.y, pose.up.z);
    camera.lookAt(pose.target.x, pose.target.y, pose.target.z);
    controlsRef.current?.target.set(
      pose.target.x,
      pose.target.y,
      pose.target.z,
    );
    controlsRef.current?.update();
    invalidate();
  }, [camera, invalidate, pose]);

  return (
    <OrbitControls
      ref={controlsRef}
      makeDefault
      enablePan
      minDistance={Math.max(0.8, Math.min(bounds.width, bounds.depth) * 0.18)}
      maxDistance={Math.max(bounds.width, bounds.depth) * 4}
      maxPolarAngle={Math.PI / 2.02}
      target={[pose.target.x, pose.target.y, pose.target.z]}
    />
  );
}
