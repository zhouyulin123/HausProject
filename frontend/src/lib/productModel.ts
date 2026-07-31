import type { SceneVector3 } from "@/types/scene";

export interface ModelDimensionsMm {
  width: number | null;
  height: number | null;
  depth: number | null;
}

export type ProductModelStatus = "missing" | "ready" | "failed";

interface ProductModelFields {
  modelUrl?: string;
  modelStatus?: ProductModelStatus;
  modelDimensionsMm?: ModelDimensionsMm;
}

export interface ProductModelAsset {
  url: string;
  dimensions: SceneVector3;
}

export function millimetersToMeters(dimensions: {
  width: number;
  height: number;
  depth: number;
}): SceneVector3 {
  return {
    x: dimensions.width / 1000,
    y: dimensions.height / 1000,
    z: dimensions.depth / 1000,
  };
}

export function getProductModelAsset(
  product: ProductModelFields,
): ProductModelAsset | null {
  const dimensions = product.modelDimensionsMm;
  if (
    product.modelStatus !== "ready" ||
    !product.modelUrl ||
    !dimensions ||
    !dimensions.width ||
    !dimensions.height ||
    !dimensions.depth ||
    dimensions.width <= 0 ||
    dimensions.height <= 0 ||
    dimensions.depth <= 0
  ) {
    return null;
  }
  return {
    url: product.modelUrl,
    dimensions: millimetersToMeters({
      width: dimensions.width,
      height: dimensions.height,
      depth: dimensions.depth,
    }),
  };
}
