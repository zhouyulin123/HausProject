import { Component, Suspense, useMemo, type ErrorInfo, type ReactNode } from "react";
import { useGLTF } from "@react-three/drei";
import { Box3, Mesh, Vector3 } from "three";
import type { SceneVector3 } from "@/types/scene";

interface ModelErrorBoundaryProps {
  fallback: ReactNode;
  children: ReactNode;
}

class ModelErrorBoundary extends Component<
  ModelErrorBoundaryProps,
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.warn("[3D] 商品模型加载失败，已降级为尺寸体块", error.message, info.componentStack);
  }

  render() {
    return this.state.failed ? this.props.fallback : this.props.children;
  }
}

function Placeholder({
  dimensions,
  color,
  selected,
}: {
  dimensions: SceneVector3;
  color: string;
  selected: boolean;
}) {
  return (
    <mesh castShadow receiveShadow>
      <boxGeometry args={[dimensions.x, dimensions.y, dimensions.z]} />
      <meshStandardMaterial
        color={selected ? "#70885E" : color}
        roughness={0.72}
        metalness={0.04}
      />
    </mesh>
  );
}

function LoadedModel({
  url,
  dimensions,
}: {
  url: string;
  dimensions: SceneVector3;
}) {
  const { scene } = useGLTF(url, false);
  const normalized = useMemo(() => {
    const clone = scene.clone(true);
    clone.traverse((object) => {
      if (object instanceof Mesh) {
        object.castShadow = true;
        object.receiveShadow = true;
      }
    });
    const bounds = new Box3().setFromObject(clone);
    const size = bounds.getSize(new Vector3());
    const center = bounds.getCenter(new Vector3());
    const safe = (value: number) => (value > 0.0001 ? value : 1);
    return {
      clone,
      position: [-center.x, -center.y, -center.z] as [number, number, number],
      scale: [
        dimensions.x / safe(size.x),
        dimensions.y / safe(size.y),
        dimensions.z / safe(size.z),
      ] as [number, number, number],
    };
  }, [dimensions.x, dimensions.y, dimensions.z, scene]);

  return (
    <group scale={normalized.scale}>
      <primitive object={normalized.clone} position={normalized.position} />
    </group>
  );
}

export default function ProductModel3D({
  url,
  dimensions,
  color,
  selected,
}: {
  url?: string;
  dimensions: SceneVector3;
  color: string;
  selected: boolean;
}) {
  const fallback = (
    <Placeholder dimensions={dimensions} color={color} selected={selected} />
  );
  if (!url) return fallback;
  return (
    <ModelErrorBoundary key={url} fallback={fallback}>
      <Suspense fallback={fallback}>
        <LoadedModel url={url} dimensions={dimensions} />
      </Suspense>
      {selected && (
        <mesh>
          <boxGeometry args={[dimensions.x * 1.02, dimensions.y * 1.02, dimensions.z * 1.02]} />
          <meshBasicMaterial color="#70885E" wireframe transparent opacity={0.72} />
        </mesh>
      )}
    </ModelErrorBoundary>
  );
}
