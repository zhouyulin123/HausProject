import type { CustomFurnitureDraftReference } from "@/lib/designProject";
import type { CustomFurnitureSpecPatch } from "@/types/customFurniture";

interface PlacementInput {
  sceneId: number;
  baseVersion: number;
  draftClientMutationId: string;
  position: { x: number; z: number };
  rotationY?: number;
}

interface PlacementRequest extends PlacementInput {
  clientMutationId: string;
}

interface PlacementCoordinatorOptions<TResult> {
  createMutationId: () => string;
  add: (request: PlacementRequest) => Promise<TResult>;
  onConflict?: () => void;
}

function placementSignature(input: PlacementInput): string {
  return JSON.stringify([
    input.sceneId,
    input.baseVersion,
    input.draftClientMutationId,
    input.position.x,
    input.position.z,
    input.rotationY ?? 0,
  ]);
}

function isConflict(error: unknown): boolean {
  return typeof error === "object"
    && error !== null
    && "status" in error
    && error.status === 409;
}

export function restoreCustomFurnitureDraftReference(
  spec: CustomFurnitureSpecPatch | null,
  reference: { client_mutation_id: string; state_version: number } | null | undefined,
): CustomFurnitureDraftReference | null {
  if (!spec || !reference) return null;
  return {
    clientMutationId: reference.client_mutation_id,
    specSignature: JSON.stringify(spec),
  };
}

export async function placeCustomFurnitureWithConflictRecovery<TResult>({
  place,
  reload,
  apply,
}: {
  place: () => Promise<TResult>;
  reload: () => Promise<TResult>;
  apply: (result: TResult) => void;
}): Promise<"placed" | "conflict_recovered"> {
  try {
    apply(await place());
    return "placed";
  } catch (error) {
    if (!isConflict(error)) throw error;
    apply(await reload());
    return "conflict_recovered";
  }
}

/** 保留结果未知请求的幂等键；场景版本变化后才开启新放置操作。 */
export function createCustomFurniturePlacementCoordinator<TResult>(
  options: PlacementCoordinatorOptions<TResult>,
) {
  let lastAttempt: { signature: string; clientMutationId: string } | null = null;
  let inFlight: { signature: string; promise: Promise<TResult> } | null = null;

  return {
    place(input: PlacementInput): Promise<TResult> {
      const signature = placementSignature(input);
      if (inFlight?.signature === signature) return inFlight.promise;
      const clientMutationId = lastAttempt?.signature === signature
        ? lastAttempt.clientMutationId
        : options.createMutationId();
      lastAttempt = { signature, clientMutationId };
      const promise = options.add({ ...input, clientMutationId })
        .then((result) => {
          if (lastAttempt?.clientMutationId === clientMutationId) {
            lastAttempt = null;
          }
          return result;
        })
        .catch((error: unknown) => {
          if (isConflict(error)) options.onConflict?.();
          throw error;
        })
        .finally(() => {
          if (inFlight?.promise === promise) inFlight = null;
        });
      inFlight = { signature, promise };
      return promise;
    },
  };
}
