import { useEffect, useMemo, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { Html, TransformControls } from "@react-three/drei";
import {
  AlertTriangle,
  ArrowDown,
  ArrowLeft,
  ArrowRight,
  ArrowUp,
  Bot,
  Box,
  Camera,
  CircleAlert,
  Cloud,
  CloudOff,
  Cpu,
  Download,
  Eye,
  LayoutGrid,
  Move3D,
  Loader2,
  Redo2,
  RefreshCw,
  Rotate3D,
  Ruler,
  Save,
  Send,
  ShieldCheck,
  Trash2,
  Undo2,
} from "lucide-react";
import { type Group } from "three";
import { useSceneEditor } from "@/hooks/useSceneEditor";
import ProductModel3D from "./ProductModel3D";
import FurnitureModel3D from "@/components/furniture/FurnitureModel3D";
import {
  openGeometryRoomCenterOffset,
  roomItemRendererKind,
} from "@/lib/openGeometryScene";
import {
  getProductAssetState,
  markInstanceGlbLoadFailed,
  productAssetLabel,
  type ProductAssetPresentation,
  type ProductAssetState,
} from "@/lib/productModel";
import { CATEGORY_COLOR } from "@/lib/scenePalette";
import {
  buildRoomFactSummary,
  getRoomCameraPose,
  type RoomCameraPreset,
} from "@/lib/roomScene";
import type { TransformMode } from "@/hooks/useSceneEditor";
import type { DesignPlan } from "@/types/design";
import type { RoomModel } from "@/types/roomModel";
import type { DesignScene, SceneItem, SceneTransform } from "@/types/scene";
import {
  sceneSyncPresentation,
  type SceneReference,
} from "@/lib/sceneEditingPolicy";
import { RoomCameraControls, RoomShell3D } from "./RoomShell3D";

interface FurnitureBoxProps {
  item: SceneItem;
  name: string;
  selected: boolean;
  mode: TransformMode;
  onSelect: () => void;
  onCommit: (transform: SceneTransform) => void;
  asset: ProductAssetState;
  onModelLoadFailure: () => void;
  editable: boolean;
}

function FurnitureBox({
  item,
  name,
  selected,
  mode,
  onSelect,
  onCommit,
  asset,
  onModelLoadFailure,
  editable,
}: FurnitureBoxProps) {
  const groupRef = useRef<Group>(null);
  const [hovered, setHovered] = useState(false);
  const dimensions = item.dimensions ?? { x: 1, y: 0.8, z: 1 };

  useEffect(() => {
    if (!hovered) return;
    document.body.style.cursor = "pointer";
    return () => {
      document.body.style.cursor = "";
    };
  }, [hovered]);

  const commitCurrentTransform = () => {
    const object = groupRef.current;
    if (!object) return;
    onCommit({
      position: {
        x: object.position.x,
        y: object.position.y,
        z: object.position.z,
      },
      rotation: {
        x: object.rotation.x,
        y: object.rotation.y,
        z: object.rotation.z,
      },
      scale: {
        x: object.scale.x,
        y: object.scale.y,
        z: object.scale.z,
      },
    });
  };

  const furniture = (
    <group
      ref={groupRef}
      position={[
        item.transform.position.x,
        item.transform.position.y,
        item.transform.position.z,
      ]}
      rotation={[
        item.transform.rotation.x,
        item.transform.rotation.y,
        item.transform.rotation.z,
      ]}
      scale={[
        item.transform.scale.x,
        item.transform.scale.y,
        item.transform.scale.z,
      ]}
    >
      <group
        onClick={(event) => {
          event.stopPropagation();
          onSelect();
        }}
        onPointerOver={(event) => {
          event.stopPropagation();
          setHovered(true);
        }}
        onPointerOut={() => setHovered(false)}
      >
        {roomItemRendererKind(item) === "open_geometry"
          && item.openGeometryModelSpec ? (
            <group position={openGeometryRoomCenterOffset(item.openGeometryModelSpec)}>
              <FurnitureModel3D spec={item.openGeometryModelSpec} />
            </group>
          ) : (
            <ProductModel3D
              url={asset.model?.url}
              dimensions={dimensions}
              color={
                hovered
                  ? "#93A77E"
                  : CATEGORY_COLOR[item.category ?? ""] ?? "#C3B49A"
              }
              selected={selected}
              onLoadFailure={onModelLoadFailure}
            />
          )}
      </group>
      {(selected || hovered) && (
        <Html
          center
          distanceFactor={8}
          position={[0, dimensions.y / 2 + 0.28, 0]}
        >
          <div
            className={`whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] font-medium shadow-sm ${
              selected
                ? "bg-sage-700 text-white"
                : "bg-stone-800/90 text-white"
            }`}
          >
            <span>{name}</span>
            <span className="ml-2 opacity-75">
              {item.sourceType === "open_geometry_draft"
                ? "开放几何 · 冻结快照"
                : productAssetLabel(asset)}
            </span>
          </div>
        </Html>
      )}
    </group>
  );

  if (!selected || !editable) return furniture;

  return (
    <TransformControls
      mode={mode}
      space="world"
      size={0.8}
      translationSnap={0.1}
      rotationSnap={Math.PI / 12}
      showX={mode === "translate"}
      showY={mode === "rotate"}
      showZ={mode === "translate"}
      onMouseUp={commitCurrentTransform}
    >
      {furniture}
    </TransformControls>
  );
}

function ToolButton({
  active = false,
  disabled = false,
  label,
  onClick,
  children,
}: {
  active?: boolean;
  disabled?: boolean;
  label: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      aria-pressed={active || undefined}
      disabled={disabled}
      onClick={onClick}
      className={`inline-flex h-9 min-w-9 items-center justify-center gap-1.5 rounded-xl px-2.5 text-xs font-medium transition-all ${
        active
          ? "bg-sage-700 text-white shadow-sm"
          : "text-stone-600 hover:bg-cream-100"
      } disabled:cursor-not-allowed disabled:opacity-35`}
    >
      {children}
    </button>
  );
}

function SyncBadge({
  state,
  warningCount,
  onReload,
  sceneReference,
}: {
  state: ReturnType<typeof useSceneEditor>["syncState"];
  warningCount: number;
  onReload: () => void;
  sceneReference: SceneReference | null;
}) {
  const content = {
    loading: {
      icon: RefreshCw,
      label: "正在恢复云端场景",
      classes: "bg-white/90 text-stone-600",
    },
    demo: {
      icon: Box,
      label: "本地演示 · 不会保存",
      classes: "bg-amber-50/95 text-amber-800",
    },
    saved: {
      icon: Cloud,
      label: "已保存到方案",
      classes: "bg-sage-50/95 text-sage-800",
    },
    dirty: {
      icon: Save,
      label: "等待自动保存",
      classes: "bg-white/95 text-stone-600",
    },
    saving: {
      icon: RefreshCw,
      label: "正在自动保存",
      classes: "bg-white/95 text-stone-600",
    },
    conflict: {
      icon: AlertTriangle,
      label: "版本冲突 · 点击恢复",
      classes: "bg-red-50/95 text-red-700",
    },
    offline: {
      icon: CloudOff,
      label: "本地编辑 · 暂未同步",
      classes: "bg-amber-50/95 text-amber-800",
    },
  }[state];
  const Icon = content.icon;
  const presentation = sceneSyncPresentation({
    syncState: state,
    sceneReference,
  });

  return (
    <button
      type="button"
      disabled={!presentation.retryable}
      onClick={onReload}
      className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-medium shadow-sm backdrop-blur ${content.classes} disabled:cursor-default`}
    >
      <Icon
        className={`h-3.5 w-3.5 ${
          state === "loading" || state === "saving" ? "animate-spin" : ""
        }`}
      />
      {presentation.label}
      {warningCount > 0 && (
        <span className="rounded-full bg-amber-200/70 px-1.5 text-[10px]">
          {warningCount} 条提醒
        </span>
      )}
    </button>
  );
}

export default function RoomView3D({
  plan,
  roomType,
  roomModel,
  onMovePersisted,
  onGlbLoadFailed,
  onSceneReferenceChange,
  onSceneSyncChange,
  authoritativeScene,
}: {
  plan: DesignPlan;
  roomType: string;
  roomModel?: RoomModel | null;
  onMovePersisted?: (move: {
    sceneId: number;
    sceneVersion: number;
    instanceId: string;
  }) => void;
  onGlbLoadFailed?: (failure: {
    planVersionId: number;
    sceneId: number;
    sceneVersion: number;
    instanceId: string;
    sku: string;
  }) => void;
  onSceneReferenceChange?: (reference: SceneReference | null) => void;
  onSceneSyncChange?: (
    state: ReturnType<typeof useSceneEditor>["syncState"],
    reference: SceneReference | null,
  ) => void;
  authoritativeScene?: DesignScene | null;
}) {
  const editor = useSceneEditor(
    plan,
    roomType,
    roomModel,
    onMovePersisted,
    onSceneReferenceChange,
  );
  const [agentInstruction, setAgentInstruction] = useState("");
  const [runtimeAssetOverrides, setRuntimeAssetOverrides] = useState<
    Record<string, ProductAssetPresentation>
  >({});
  const reportedAssetFailures = useRef(new Set<string>());
  const [cameraPreset, setCameraPreset] =
    useState<RoomCameraPreset>("perspective");
  const scene = editor.history.present;

  useEffect(() => {
    onSceneSyncChange?.(editor.syncState, editor.sceneReference);
  }, [
    editor.sceneReference,
    editor.syncState,
    onSceneSyncChange,
  ]);

  useEffect(() => {
    if (authoritativeScene) editor.applyAuthoritativeScene(authoritativeScene);
  }, [authoritativeScene, editor.applyAuthoritativeScene]);

  useEffect(() => {
    setRuntimeAssetOverrides({});
    reportedAssetFailures.current.clear();
  }, [plan.planVersionId]);
  const roomFacts = useMemo(
    () => buildRoomFactSummary(scene, roomModel),
    [roomModel, scene],
  );
  const initialCamera = useMemo(
    () => getRoomCameraPose(scene, "perspective"),
    [scene],
  );
  const selectedItem = scene.items.find(
    (item) => item.instanceId === editor.selectedItemId,
  );
  const selectedFurniture = selectedItem
    ? plan.furnitureSuggestions.find(
        (item) =>
          item.sku === selectedItem.sku ||
          selectedItem.sku.endsWith(item.id),
      )
    : null;

  const itemNames = useMemo(
    () =>
      Object.fromEntries(
        scene.items.map((sceneItem) => {
          const furniture = plan.furnitureSuggestions.find(
            (item) =>
              item.sku === sceneItem.sku || sceneItem.sku.endsWith(item.id),
          );
          return [
            sceneItem.instanceId,
            furniture?.name ?? sceneItem.category ?? sceneItem.sku,
          ];
        }),
      ),
    [plan.furnitureSuggestions, scene.items],
  );
  const itemAssets = useMemo(
    () =>
      Object.fromEntries(
        scene.items.map((sceneItem) => {
          const furniture = plan.furnitureSuggestions.find(
            (item) =>
              item.sku === sceneItem.sku || sceneItem.sku.endsWith(item.id),
          );
          const declaredAsset = getProductAssetState({
            ...furniture,
            assetMode: sceneItem.assetMode ?? furniture?.assetMode,
            fallbackReason:
              sceneItem.fallbackReason ?? furniture?.fallbackReason,
          });
          const runtimeOverride = runtimeAssetOverrides[sceneItem.instanceId];
          return [
            sceneItem.instanceId,
            runtimeOverride
              ? { ...runtimeOverride, model: null }
              : declaredAsset,
          ];
        }),
      ),
    [plan.furnitureSuggestions, runtimeAssetOverrides, scene.items],
  );

  const handleModelLoadFailure = (instanceId: string) => {
    setRuntimeAssetOverrides((current) => {
      const seeded = current[instanceId]
        ? current
        : {
            ...current,
            [instanceId]: {
              assetMode: itemAssets[instanceId].assetMode,
              fallbackReason: itemAssets[instanceId].fallbackReason,
            },
          };
      return markInstanceGlbLoadFailed(seeded, instanceId);
    });
  };

  useEffect(() => {
    if (!plan.planVersionId || !editor.sceneReference) return;
    for (const [instanceId, asset] of Object.entries(runtimeAssetOverrides)) {
      if (asset.fallbackReason !== "glb_load_failed") continue;
      const failedItem = scene.items.find(
        (item) => item.instanceId === instanceId,
      );
      if (!failedItem) continue;
      const evidenceKey = [
        plan.planVersionId,
        editor.sceneReference.id,
        editor.sceneReference.version,
        instanceId,
        failedItem.sku,
      ].join(":");
      if (reportedAssetFailures.current.has(evidenceKey)) continue;
      reportedAssetFailures.current.add(evidenceKey);
      onGlbLoadFailed?.({
        planVersionId: plan.planVersionId,
        sceneId: editor.sceneReference.id,
        sceneVersion: editor.sceneReference.version,
        instanceId,
        sku: failedItem.sku,
      });
    }
  }, [
    editor.sceneReference,
    onGlbLoadFailed,
    plan.planVersionId,
    runtimeAssetOverrides,
    scene.items,
  ]);

  useEffect(() => {
    const timer = window.setTimeout(
      () => window.dispatchEvent(new Event("resize")),
      60,
    );
    return () => window.clearTimeout(timer);
  }, []);

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const modifier = event.ctrlKey || event.metaKey;
    if (modifier && event.key.toLowerCase() === "z") {
      event.preventDefault();
      if (event.shiftKey) editor.redo();
      else editor.undo();
      return;
    }
    if (modifier && event.key.toLowerCase() === "y") {
      event.preventDefault();
      editor.redo();
      return;
    }
    if (!editor.selectedItemId) return;
    const directions: Record<string, [number, number]> = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
    };
    const direction = directions[event.key];
    if (direction) {
      event.preventDefault();
      const multiplier = event.shiftKey ? 5 : 1;
      editor.nudgeSelected(
        direction[0] * multiplier,
        direction[1] * multiplier,
      );
    } else if (event.key.toLowerCase() === "r") {
      event.preventDefault();
      editor.rotateSelected();
    } else if (event.key === "Escape") {
      editor.selectItem(null);
    }
  };

  const agentDisabled =
    editor.sceneAgentState === "thinking" ||
    ["loading", "saving", "demo", "offline", "conflict"].includes(
      editor.syncState,
    );
  const renderActive = ["queued", "running"].includes(
    editor.blenderRenderJob?.status ?? "",
  );
  const renderDisabled =
    editor.blenderRenderPending ||
    renderActive ||
    editor.sceneAgentState === "thinking" ||
    ["loading", "saving", "demo", "offline", "conflict"].includes(
      editor.syncState,
    );

  return (
    <div className="space-y-3">
      <section
        aria-label="数字房间空间事实"
        className="border-y border-cream-200 bg-white/55 px-1 py-3"
      >
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold text-stone-800">
                {scene.room.name}数字房间
              </h3>
              <span
                className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${
                  roomModel?.scale.source === "user"
                    ? "bg-sage-100 text-sage-800"
                    : "bg-amber-100 text-amber-800"
                }`}
              >
                {roomFacts.scaleLabel}
              </span>
            </div>
            <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-xs text-stone-500">
              <span className="inline-flex items-center gap-1">
                <Ruler className="h-3.5 w-3.5" />
                {roomFacts.dimensionsLabel}
              </span>
              <span>{roomFacts.openingCount} 个门窗/开口</span>
              <span>空间置信度 {roomFacts.confidenceLabel}</span>
            </div>
          </div>
          <div className="flex flex-wrap justify-end gap-2 text-[10px]">
            {roomFacts.fixedObstacleCount > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-stone-100 px-2.5 py-1 text-stone-600">
                <CircleAlert className="h-3 w-3" />
                固定障碍：{roomFacts.obstacleNames.join("、")}（位置待确认）
              </span>
            )}
            {roomFacts.pendingConfirmationCount > 0 && (
              <span className="rounded-full bg-amber-50 px-2.5 py-1 text-amber-800">
                {roomFacts.pendingConfirmationCount} 项空间事实待确认
              </span>
            )}
            <span
              className={`rounded-full px-2.5 py-1 ${
                editor.validation?.valid === false
                  ? "bg-red-50 text-red-700"
                  : "bg-sage-50 text-sage-800"
              }`}
            >
              {editor.validation?.valid === false
                ? `${editor.validation.errors.length} 项空间冲突`
                : editor.validation
                  ? "空间校验通过"
                  : "本地边界保护已开启"}
            </span>
          </div>
        </div>
      </section>
      <div
        role="application"
        aria-label="3D 空间编辑器"
        tabIndex={0}
        onKeyDown={handleKeyDown}
        className="relative h-[620px] overflow-hidden rounded-[28px] border border-cream-200 bg-[#ded5c5] shadow-[0_24px_70px_rgba(86,70,47,0.16)] outline-none focus-visible:ring-2 focus-visible:ring-sage-500"
      >
      <Canvas
        shadows
        frameloop="demand"
        gl={{ preserveDrawingBuffer: true, antialias: true }}
        camera={{
          position: [
            initialCamera.position.x,
            initialCamera.position.y,
            initialCamera.position.z,
          ],
          fov: scene.camera?.fov ?? 45,
        }}
        onPointerMissed={() => editor.selectItem(null)}
      >
        <color attach="background" args={["#DED5C5"]} />
        <fog attach="fog" args={["#DED5C5", 11, 23]} />
        <ambientLight intensity={0.82} />
        <directionalLight
          position={[4, 8, 5]}
          intensity={1.15}
          castShadow
          shadow-mapSize-width={1024}
          shadow-mapSize-height={1024}
        />
        <RoomShell3D scene={scene} />
        {scene.items.map((item) => (
          <FurnitureBox
            key={item.instanceId}
            item={item}
            name={itemNames[item.instanceId]}
            selected={editor.selectedItemId === item.instanceId}
            mode={editor.transformMode}
            onSelect={() => editor.selectItem(item.instanceId)}
            onCommit={(transform) =>
              editor.commitTransform(
                item.instanceId,
                transform,
                editor.transformMode === "translate",
              )
            }
            asset={itemAssets[item.instanceId]}
            onModelLoadFailure={() => handleModelLoadFailure(item.instanceId)}
            editable={!editor.editingBlocked}
          />
        ))}
        <RoomCameraControls scene={scene} preset={cameraPreset} />
      </Canvas>

      <div className="absolute top-16 left-4 sm:top-4">
        <SyncBadge
          state={editor.syncState}
          warningCount={editor.validation?.warnings.length ?? 0}
          onReload={() => void editor.reload()}
          sceneReference={editor.sceneReference}
        />
      </div>

      <div className="absolute top-4 left-4 flex items-center gap-1 rounded-2xl border border-white/60 bg-white/90 p-1 shadow-lg backdrop-blur-md sm:left-1/2 sm:-translate-x-1/2">
        <ToolButton
          label="移动家具"
          active={editor.transformMode === "translate"}
          disabled={editor.editingBlocked}
          onClick={() => editor.setTransformMode("translate")}
        >
          <Move3D className="h-4 w-4" />
          <span className="hidden sm:inline">移动</span>
        </ToolButton>
        <ToolButton
          label="旋转家具"
          active={editor.transformMode === "rotate"}
          disabled={editor.editingBlocked}
          onClick={() => editor.setTransformMode("rotate")}
        >
          <Rotate3D className="h-4 w-4" />
          <span className="hidden sm:inline">旋转</span>
        </ToolButton>
        <span className="mx-0.5 h-5 w-px bg-stone-200" />
        <ToolButton
          label="撤销（Ctrl+Z）"
          disabled={editor.editingBlocked || !editor.history.canUndo}
          onClick={editor.undo}
        >
          <Undo2 className="h-4 w-4" />
        </ToolButton>
        <ToolButton
          label="重做（Ctrl+Y）"
          disabled={editor.editingBlocked || !editor.history.canRedo}
          onClick={editor.redo}
        >
          <Redo2 className="h-4 w-4" />
        </ToolButton>
      </div>

      <div
        role="group"
        aria-label="3D 视角"
        className={`absolute left-4 flex items-center gap-1 rounded-xl border border-white/60 bg-white/90 p-1 shadow-lg backdrop-blur-md ${
          selectedItem ? "bottom-[276px] sm:bottom-4" : "bottom-4"
        }`}
      >
        <ToolButton
          label="全景视角"
          active={cameraPreset === "perspective"}
          onClick={() => setCameraPreset("perspective")}
        >
          <Box className="h-4 w-4" />
          <span className="hidden sm:inline">全景</span>
        </ToolButton>
        <ToolButton
          label="俯视平面"
          active={cameraPreset === "top"}
          onClick={() => setCameraPreset("top")}
        >
          <LayoutGrid className="h-4 w-4" />
          <span className="hidden sm:inline">俯视</span>
        </ToolButton>
        <ToolButton
          label="室内视角"
          active={cameraPreset === "inside"}
          onClick={() => setCameraPreset("inside")}
        >
          <Eye className="h-4 w-4" />
          <span className="hidden sm:inline">室内</span>
        </ToolButton>
      </div>

      <div className="pointer-events-none absolute bottom-4 left-1/2 hidden -translate-x-1/2 rounded-full border border-white/50 bg-stone-900/72 px-3 py-1.5 text-[11px] text-white/90 backdrop-blur md:block">
        点击家具开始编辑 · 拖动画布查看空间 · 滚轮缩放
      </div>

      {selectedItem && (
        <aside className="absolute right-4 bottom-4 w-[min(250px,calc(100%-2rem))] rounded-2xl border border-white/70 bg-white/92 p-4 shadow-xl backdrop-blur-md">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-[10px] font-semibold tracking-[0.16em] text-sage-700 uppercase">
                Selected
              </p>
              <h3 className="mt-1 line-clamp-2 text-sm font-semibold text-stone-800">
                {selectedFurniture?.name ??
                  selectedItem.category ??
                  selectedItem.sku}
              </h3>
              <p className="mt-1 font-mono text-[10px] text-stone-400">
                {selectedItem.sku}
              </p>
              <p className="mt-1 text-[10px] font-medium text-stone-500">
                {selectedItem.sourceType === "custom_furniture_draft"
                  ? "参数化定制草稿 · 非正式商品"
                  : selectedItem.sourceType === "open_geometry_draft"
                    ? `开放几何 V${selectedItem.openGeometryRef?.openGeometryVersion ?? "?"} · 冻结快照`
                    : productAssetLabel(itemAssets[selectedItem.instanceId])}
              </p>
            </div>
            <Box className="h-5 w-5 shrink-0 text-wood-500" />
          </div>

          <div className="mt-3 grid grid-cols-3 gap-1 text-center font-mono text-[10px] text-stone-500">
            <span className="rounded-lg bg-cream-50 px-1 py-1.5">
              X {selectedItem.transform.position.x.toFixed(2)}
            </span>
            <span className="rounded-lg bg-cream-50 px-1 py-1.5">
              Z {selectedItem.transform.position.z.toFixed(2)}
            </span>
            <span className="rounded-lg bg-cream-50 px-1 py-1.5">
              R{" "}
              {Math.round(
                (selectedItem.transform.rotation.y * 180) / Math.PI,
              )}
              °
            </span>
          </div>

          <div className="mt-3 grid grid-cols-3 gap-1">
            <span />
            <ToolButton
              label="向后移动 10 厘米"
              disabled={editor.editingBlocked}
              onClick={() => editor.nudgeSelected(0, -1)}
            >
              <ArrowUp className="h-4 w-4" />
            </ToolButton>
            <span />
            <ToolButton
              label="向左移动 10 厘米"
              disabled={editor.editingBlocked}
              onClick={() => editor.nudgeSelected(-1, 0)}
            >
              <ArrowLeft className="h-4 w-4" />
            </ToolButton>
            <ToolButton
              label="顺时针旋转 15 度"
              disabled={editor.editingBlocked}
              onClick={() => editor.rotateSelected()}
            >
              <Rotate3D className="h-4 w-4" />
            </ToolButton>
            <ToolButton
              label="向右移动 10 厘米"
              disabled={editor.editingBlocked}
              onClick={() => editor.nudgeSelected(1, 0)}
            >
              <ArrowRight className="h-4 w-4" />
            </ToolButton>
            <span />
            <ToolButton
              label="向前移动 10 厘米"
              disabled={editor.editingBlocked}
              onClick={() => editor.nudgeSelected(0, 1)}
            >
              <ArrowDown className="h-4 w-4" />
            </ToolButton>
            <span />
          </div>
          {(selectedItem.sourceType === "custom_furniture_draft"
            || selectedItem.sourceType === "open_geometry_draft") && (
            <button
              type="button"
              title="从当前房间删除"
              disabled={editor.editingBlocked}
              onClick={editor.removeSelected}
              className="mt-3 inline-flex min-h-9 w-full items-center justify-center gap-2 border border-red-200 bg-red-50 px-3 text-xs font-medium text-red-700 transition-colors hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-45"
            >
              <Trash2 className="h-4 w-4" />
              从房间删除
            </button>
          )}
        </aside>
      )}
    </div>
      <section
        aria-label="Scene Agent 空间优化"
        className="rounded-2xl border border-cream-200 bg-white/85 p-4 shadow-card"
      >
        <div className="flex items-start gap-3">
          <div className="rounded-xl bg-sage-50 p-2 text-sage-700">
            <Bot className="h-5 w-5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h3 className="text-sm font-semibold text-stone-800">
                Scene Agent
              </h3>
              <span className="inline-flex items-center gap-1 rounded-full bg-cream-100 px-2 py-0.5 text-[10px] text-stone-500">
                <ShieldCheck className="h-3 w-3" />
                碰撞 · 越界 · 门口动线检查
              </span>
            </div>
            <p className="mt-1 text-xs leading-relaxed text-stone-400">
              用自然语言调整当前空间，例如“把沙发向左移 30 厘米”或“增加一把餐椅”。
              AI 只生成白名单操作，通过安全检查后才会保存新版本。
            </p>
          </div>
        </div>
        <form
          className="mt-3 flex flex-col gap-2 sm:flex-row"
          onSubmit={(event) => {
            event.preventDefault();
            void editor.runSceneAgent(agentInstruction);
          }}
        >
          <input
            value={agentInstruction}
            onChange={(event) => setAgentInstruction(event.target.value)}
            maxLength={1000}
            disabled={agentDisabled}
            placeholder={
              editor.syncState === "demo"
                ? "生成正式方案后可使用 Scene Agent"
                : "描述你想怎样调整家具布局"
            }
            aria-label="Scene Agent 调整指令"
            className="min-w-0 flex-1 rounded-xl border border-cream-300 bg-white px-3.5 py-2.5 text-sm text-stone-700 outline-none placeholder:text-stone-300 focus:border-sage-500 focus:ring-2 focus:ring-sage-100 disabled:cursor-not-allowed disabled:bg-cream-50"
          />
          <button
            type="submit"
            disabled={agentDisabled || agentInstruction.trim().length < 2}
            className="inline-flex items-center justify-center gap-2 rounded-xl bg-sage-700 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-sage-800 disabled:cursor-not-allowed disabled:opacity-45"
          >
            {editor.sceneAgentState === "thinking" ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
            {editor.sceneAgentState === "thinking" ? "正在规划" : "执行调整"}
          </button>
        </form>
        {editor.sceneAgentMessage && (
          <p
            role="status"
            className={`mt-2 rounded-xl px-3 py-2 text-xs ${
              editor.sceneAgentState === "done"
                ? "bg-sage-50 text-sage-800"
                : editor.sceneAgentState === "blocked"
                  ? "bg-amber-50 text-amber-800"
                  : editor.sceneAgentState === "error"
                    ? "bg-red-50 text-red-700"
                    : "bg-cream-50 text-stone-500"
            }`}
          >
            {editor.sceneAgentMessage}
          </p>
        )}
      </section>
      <section
        aria-label="Blender 高质量渲染"
        className="overflow-hidden rounded-2xl border border-cream-200 bg-white/85 shadow-card"
      >
        <div className="grid gap-4 p-4 lg:grid-cols-[1fr_auto] lg:items-center">
          <div className="flex items-start gap-3">
            <div className="rounded-xl bg-terra-50 p-2 text-terra-700">
              <Camera className="h-5 w-5" />
            </div>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="text-sm font-semibold text-stone-800">
                  Blender 高质量渲染
                </h3>
                <span className="inline-flex items-center gap-1 rounded-full bg-stone-100 px-2 py-0.5 text-[10px] text-stone-500">
                  <Cpu className="h-3 w-3" />
                  独立进程 · 静态可信脚本
                </span>
              </div>
              <p className="mt-1 max-w-2xl text-xs leading-relaxed text-stone-400">
                将当前不可变场景版本提交给隔离 Worker。预览档使用 Eevee，
                成片档使用 Cycles，并优先启用 NVIDIA OptiX。
              </p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button
              type="button"
              disabled={renderDisabled}
              onClick={() => void editor.queueBlenderRender("preview")}
              className="rounded-xl border border-cream-300 bg-white px-3.5 py-2 text-xs font-medium text-stone-600 transition-colors hover:border-sage-400 hover:text-sage-700 disabled:cursor-not-allowed disabled:opacity-45"
            >
              快速预览
            </button>
            <button
              type="button"
              disabled={renderDisabled}
              onClick={() => void editor.queueBlenderRender("final")}
              className="inline-flex items-center gap-1.5 rounded-xl bg-terra-600 px-3.5 py-2 text-xs font-medium text-white transition-colors hover:bg-terra-700 disabled:cursor-not-allowed disabled:opacity-45"
            >
              {editor.blenderRenderPending || renderActive ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Camera className="h-3.5 w-3.5" />
              )}
              Cycles 成片
            </button>
          </div>
        </div>
        {editor.blenderRenderMessage && (
          <div className="border-t border-cream-100 bg-cream-50/70 px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p role="status" className="text-xs text-stone-600">
                {editor.blenderRenderMessage}
              </p>
              {editor.blenderRenderJob?.output_url && (
                <a
                  href={editor.blenderRenderJob.output_url}
                  download
                  className="inline-flex items-center gap-1 text-xs font-medium text-sage-700 hover:text-sage-800"
                >
                  <Download className="h-3.5 w-3.5" />
                  下载 PNG
                </a>
              )}
            </div>
            {renderActive && (
              <div
                role="progressbar"
                aria-label="Blender 渲染进度"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={editor.blenderRenderJob?.progress ?? 0}
                className="mt-2 h-1.5 overflow-hidden rounded-full bg-cream-200"
              >
                <div
                  className="h-full rounded-full bg-terra-500 transition-[width]"
                  style={{
                    width: `${editor.blenderRenderJob?.progress ?? 0}%`,
                  }}
                />
              </div>
            )}
          </div>
        )}
        {editor.blenderRenderJob?.status === "completed" &&
          editor.blenderRenderJob.output_url && (
            <img
              src={editor.blenderRenderJob.output_url}
              alt={`场景版本 ${editor.blenderRenderJob.scene_version} 的 Blender 效果图`}
              className="max-h-[520px] w-full border-t border-cream-100 object-cover"
            />
          )}
      </section>
    </div>
  );
}
