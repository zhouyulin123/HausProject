const CHUNK_BY_PACKAGE: Readonly<Record<string, string>> = {
  react: "vendor-react",
  "react-dom": "vendor-react",
  "react-router": "vendor-react",
  "react-router-dom": "vendor-react",
  "react-reconciler": "vendor-react",
  scheduler: "vendor-react",
  three: "vendor-three",
  "@react-three/fiber": "vendor-react-three",
  "@react-three/drei": "vendor-react-three",
  "@react-spring/three": "vendor-react-three",
  "@react-spring/core": "vendor-react-three",
  "@react-spring/shared": "vendor-react-three",
  "@use-gesture/react": "vendor-react-three",
  "@use-gesture/core": "vendor-react-three",
  "framer-motion": "vendor-motion",
  "lucide-react": "vendor-icons",
};

function packageNameFromModuleId(moduleId: string): string | undefined {
  const normalizedId = moduleId.replace(/\\/g, "/");
  const marker = "/node_modules/";
  const markerIndex = normalizedId.lastIndexOf(marker);
  if (markerIndex < 0) return undefined;

  const packagePath = normalizedId.slice(markerIndex + marker.length);
  const segments = packagePath.split("/");
  if (!segments[0]) return undefined;
  return segments[0].startsWith("@") && segments[1]
    ? `${segments[0]}/${segments[1]}`
    : segments[0];
}

export function chunkGroupForModule(moduleId: string): string | undefined {
  const packageName = packageNameFromModuleId(moduleId);
  return packageName ? CHUNK_BY_PACKAGE[packageName] : undefined;
}
