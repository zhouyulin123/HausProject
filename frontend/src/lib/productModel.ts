import type {
  AssetFallbackReason,
  AssetMode,
  SceneVector3,
} from "@/types/scene";

export interface ModelDimensionsMm {
  width: number | null;
  height: number | null;
  depth: number | null;
}

export type ProductModelStatus =
  | "missing"
  | "pending_review"
  | "ready"
  | "rejected"
  | "failed";

interface ProductModelFields {
  assetMode?: AssetMode;
  fallbackReason?: AssetFallbackReason | null;
  modelUrl?: string;
  modelStatus?: ProductModelStatus;
  modelDimensionsMm?: ModelDimensionsMm;
}

export interface ProductModelAsset {
  url: string;
  dimensions: SceneVector3;
}

export interface ProductAssetPresentation {
  assetMode: AssetMode;
  fallbackReason: AssetFallbackReason | null;
}

export interface ProductAssetState extends ProductAssetPresentation {
  model: ProductModelAsset | null;
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
    product.assetMode !== "approved_glb" ||
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

/** 前端只消费服务端显式裁决；旧数据缺字段时保守使用参数化体块。 */
export function getProductAssetState(
  product: ProductModelFields,
): ProductAssetState {
  if (!product.assetMode) {
    return {
      assetMode: "parametric",
      fallbackReason: "asset_contract_missing",
      model: null,
    };
  }

  if (product.assetMode === "approved_glb") {
    const model = getProductModelAsset(product);
    return model
      ? { assetMode: "approved_glb", fallbackReason: null, model }
      : {
          assetMode: "fallback",
          fallbackReason: "glb_metadata_invalid",
          model: null,
        };
  }

  return {
    assetMode: product.assetMode,
    fallbackReason: product.fallbackReason ?? null,
    model: null,
  };
}

export function markInstanceGlbLoadFailed(
  current: Record<string, ProductAssetPresentation>,
  instanceId: string,
): Record<string, ProductAssetPresentation> {
  if (!current[instanceId]) return current;
  return {
    ...current,
    [instanceId]: {
      assetMode: "fallback",
      fallbackReason: "glb_load_failed",
    },
  };
}

export function productAssetLabel(asset: ProductAssetPresentation): string {
  if (asset.assetMode === "approved_glb") return "审核通过 GLB";
  if (asset.fallbackReason === "glb_load_failed") {
    return "GLB 加载失败，已使用参数化体块";
  }
  if (asset.fallbackReason === "glb_pending_review") {
    return "GLB 待审核，使用参数化体块";
  }
  return asset.assetMode === "fallback"
    ? "GLB 不可用，已使用参数化体块"
    : "参数化体块";
}
