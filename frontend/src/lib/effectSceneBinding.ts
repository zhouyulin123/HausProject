import { loadOrCreateDesignScene } from "@/api/designApi";
import type { DesignPlan } from "@/types/design";
import type { RoomModel } from "@/types/roomModel";
import type { DesignScene } from "@/types/scene";
import type { SceneSyncState } from "./sceneEditingPolicy";
import { buildSceneDocument } from "./sceneDocument";

export interface EffectSceneBinding {
  syncState: SceneSyncState;
  sceneId: number | null;
  sceneVersion: number | null;
}

interface ResolveEffectSceneBindingOptions {
  plan: DesignPlan;
  primaryRoom: string;
  roomModel: RoomModel | null;
  loadOrCreate?: (
    planVersionId: number,
    initialScene: ReturnType<typeof buildSceneDocument>,
  ) => Promise<DesignScene>;
}

/** 正式方案必须恢复或创建权威场景；仅本地方案可以进入 demo。 */
export async function resolveEffectSceneBinding({
  plan,
  primaryRoom,
  roomModel,
  loadOrCreate = loadOrCreateDesignScene,
}: ResolveEffectSceneBindingOptions): Promise<EffectSceneBinding> {
  if (!plan.planVersionId) {
    return { syncState: "demo", sceneId: null, sceneVersion: null };
  }
  try {
    const scene = await loadOrCreate(
      plan.planVersionId,
      buildSceneDocument(plan, primaryRoom, roomModel),
    );
    return {
      syncState: "saved",
      sceneId: scene.id,
      sceneVersion: scene.current_version,
    };
  } catch {
    return { syncState: "offline", sceneId: null, sceneVersion: null };
  }
}
