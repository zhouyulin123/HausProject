import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { OrbitControls } from "@react-three/drei";
import { Link } from "react-router-dom";
import {
  ArrowLeft,
  Bot,
  Loader2,
  MessageCircleMore,
  Send,
  X,
} from "lucide-react";
import { Shape } from "three";
import {
  fetchFurnitureCatalog,
  runDemoAgentCommand,
  type DemoConversationTurn,
} from "@/api/designApi";
import type { FurnitureItem } from "@/types/furniture";
import type { SceneDocument } from "@/types/scene";
import FurnitureModel3D from "@/components/furniture/FurnitureModel3D";
import {
  demoItemRenderY,
  findAffectedInstanceIds,
} from "@/lib/demoScene";

type SpaceName = "客厅" | "卧室" | "餐厅";

const SPACES: SpaceName[] = ["客厅", "卧室", "餐厅"];

const ROOM_SIZES: Record<SpaceName, { width: number; depth: number }> = {
  客厅: { width: 4.6, depth: 5.6 },
  卧室: { width: 3.6, depth: 4.2 },
  餐厅: { width: 3.6, depth: 3.8 },
};

interface Placement {
  sku: string;
  position: [number, number, number];
  rotationY?: number;
}

/** 每个空间选品 + 摆放位置（y=0 落地；吊灯吸顶 2.8m / 环形吊灯 1.6m）。 */
const DEMO_LAYOUTS: Record<SpaceName, Placement[]> = {
  客厅: [
    { sku: "SF-001", position: [0, 0, -2.2] },
    { sku: "CJ-001", position: [0, 0, -1.1] },
    { sku: "DG-001", position: [-1.9, 0, -2.3] },
    { sku: "DT-001", position: [0, 0, -1.0] },
  ],
  卧室: [
    { sku: "CH-002", position: [0, 0, -1.05] },
    { sku: "CT-001", position: [-1.15, 0, -1.05] },
    { sku: "CT-001", position: [1.15, 0, -1.05] },
    { sku: "DG-002", position: [-1.5, 2.8, -1.05] },
  ],
  餐厅: [
    { sku: "ZY-002", position: [0, 0, 0] },
    { sku: "CY-001", position: [0, 0, -0.75] },
    { sku: "CY-001", position: [0, 0, 0.75], rotationY: Math.PI },
    { sku: "CY-001", position: [-0.95, 0, 0], rotationY: Math.PI / 2 },
    { sku: "CY-001", position: [0.95, 0, 0], rotationY: -Math.PI / 2 },
    { sku: "DG-003", position: [0, 2.8, 0] },
  ],
};

function buildInitialScene(space: SpaceName): SceneDocument {
  const { width, depth } = ROOM_SIZES[space];
  return {
    schemaVersion: "1.0",
    unit: "m",
    coordinateSystem: "right-handed-y-up",
    room: {
      id: `demo-${space}`,
      name: space,
      floorPolygon: [
        { x: -width / 2, z: -depth / 2 },
        { x: width / 2, z: -depth / 2 },
        { x: width / 2, z: depth / 2 },
        { x: -width / 2, z: depth / 2 },
      ],
      ceilingHeight: 2.8,
      wallThickness: 0.12,
    },
    openings: [],
    items: DEMO_LAYOUTS[space].map((placement, index) => ({
      instanceId: `item-${placement.sku}-${index + 1}`,
      sku: placement.sku,
      category: null,
      transform: {
        position: {
          x: placement.position[0],
          y: placement.position[1],
          z: placement.position[2],
        },
        rotation: { x: 0, y: placement.rotationY ?? 0, z: 0 },
        scale: { x: 1, y: 1, z: 1 },
      },
    })),
  };
}

function RoomFloor({ width, depth }: { width: number; depth: number }) {
  const shape = useMemo(() => {
    const s = new Shape();
    const hw = width / 2;
    const hd = depth / 2;
    s.moveTo(-hw, -hd);
    s.lineTo(hw, -hd);
    s.lineTo(hw, hd);
    s.lineTo(-hw, hd);
    s.closePath();
    return s;
  }, [width, depth]);

  return (
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -0.002, 0]} receiveShadow>
      <shapeGeometry args={[shape]} />
      <meshStandardMaterial color="#E4D3B8" roughness={0.92} />
    </mesh>
  );
}

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

/** 全屏 demo 3D 展示页：真实家具 + AI 多轮对话改布局（线上 3D 入口）。 */
export default function Demo3DPage() {
  const [space, setSpace] = useState<SpaceName>("客厅");
  const [scene, setScene] = useState<SceneDocument>(() =>
    buildInitialScene("客厅"),
  );
  const [catalog, setCatalog] = useState<FurnitureItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(true);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [conversationHistory, setConversationHistory] = useState<
    DemoConversationTurn[]
  >([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const chatListRef = useRef<HTMLDivElement>(null);
  const requestVersionRef = useRef(0);

  const loadCatalog = useCallback(async () => {
    const requiredSkus = new Set(
      Object.values(DEMO_LAYOUTS).flatMap((placements) =>
        placements.map((placement) => placement.sku),
      ),
    );
    setLoading(true);
    setCatalogError(null);
    try {
      const items = await fetchFurnitureCatalog({ fallbackToMock: false });
      const available = new Set(
        items.filter((item) => item.modelSpecJson).map((item) => item.sku),
      );
      const missing = [...requiredSkus].filter((sku) => !available.has(sku));
      if (missing.length) {
        throw new Error(`以下演示商品缺少 3D 参数：${missing.join("、")}`);
      }
      setCatalog(items);
    } catch (error) {
      setCatalog([]);
      setCatalogError(
        error instanceof Error ? error.message : "商品库加载失败，请稍后重试",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadCatalog();
  }, [loadCatalog]);

  useEffect(() => {
    chatListRef.current?.scrollTo({
      top: chatListRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  const { width, depth } = ROOM_SIZES[space];

  const switchSpace = (next: SpaceName) => {
    requestVersionRef.current += 1;
    setSpace(next);
    setScene(buildInitialScene(next));
    setMessages([]);
    setConversationHistory([]);
    setSending(false);
  };

  const handleSend = async () => {
    const instruction = input.trim();
    if (!instruction || sending) return;
    setInput("");
    setMessages((prev) => [...prev, { role: "user", content: instruction }]);
    setSending(true);
    const requestVersion = ++requestVersionRef.current;
    const sourceScene = scene;
    try {
      const result = await runDemoAgentCommand(
        instruction,
        sourceScene,
        conversationHistory,
      );
      if (requestVersion !== requestVersionRef.current) return;
      const affectedInstanceIds = findAffectedInstanceIds(
        sourceScene.items.map((item) => item.instanceId),
        result.scene.items.map((item) => item.instanceId),
        result.operations,
      );
      setScene(result.scene);
      setConversationHistory((previous) => [
        ...previous.slice(-7),
        {
          instruction,
          message: result.message,
          operations: result.operations,
          affectedInstanceIds,
        },
      ]);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: result.message },
      ]);
    } catch (error) {
      if (requestVersion !== requestVersionRef.current) return;
      const message =
        error instanceof Error && error.message.includes("429")
          ? "操作太频繁了，请稍后再试。"
          : error instanceof Error && error.message.includes("422")
            ? "这个调整会造成越界或碰撞，请换个位置再试。"
            : "AI 服务暂时不可用，请稍后再试。";
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: message },
      ]);
    } finally {
      if (requestVersion === requestVersionRef.current) setSending(false);
    }
  };

  const cameraPosition: [number, number, number] = [
    width * 1.1,
    depth * 0.75,
    depth * 1.15,
  ];

  return (
    <div className="relative h-screen w-screen overflow-hidden bg-[#E7DECF]">
      <Canvas
        shadows
        frameloop="always"
        gl={{ antialias: true }}
        camera={{ position: cameraPosition, fov: 45 }}
      >
        <color attach="background" args={["#E7DECF"]} />
        <ambientLight intensity={0.8} />
        <directionalLight position={[4, 8, 5]} intensity={1.2} />
        <RoomFloor width={width} depth={depth} />
        {scene.items.map((item) => {
          const furniture = catalog.find((f) => f.sku === item.sku);
          if (!furniture?.modelSpecJson) return null;
          return (
            <group
              key={item.instanceId}
              position={[
                item.transform.position.x,
                demoItemRenderY(furniture, scene.room.ceilingHeight),
                item.transform.position.z,
              ]}
              rotation={[0, item.transform.rotation.y, 0]}
            >
              <FurnitureModel3D spec={furniture.modelSpecJson} />
            </group>
          );
        })}
        <OrbitControls
          makeDefault
          enablePan={false}
          minDistance={3}
          maxDistance={16}
          maxPolarAngle={Math.PI / 2.05}
          target={[0, 0.5, 0]}
        />
      </Canvas>

      {/* 顶部：返回 + 空间切换 */}
      <div className="absolute top-4 left-4 flex items-center gap-3 sm:top-6 sm:left-6">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 rounded-full bg-white/85 px-3.5 py-2 text-sm font-medium text-stone-700 shadow-sm backdrop-blur transition-colors hover:bg-white"
        >
          <ArrowLeft className="h-4 w-4" />
          返回首页
        </Link>
        <div className="grid grid-cols-3 gap-1 rounded-full bg-white/85 p-1 shadow-sm backdrop-blur">
          {SPACES.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => switchSpace(option)}
              className={`rounded-full px-3.5 py-1.5 text-sm font-medium transition-colors ${
                space === option
                  ? "bg-sage-700 text-white"
                  : "text-stone-600 hover:bg-cream-100"
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      </div>

      {/* 底部提示 */}
      <div className="pointer-events-none absolute bottom-5 left-1/2 -translate-x-1/2 rounded-full bg-stone-900/60 px-4 py-1.5 text-xs text-white/85 backdrop-blur">
        拖动旋转 · 滚轮缩放 · 右下角 AI 对话改布局
      </div>

      {/* AI 对话按钮 */}
      {!chatOpen && (
        <button
          type="button"
          onClick={() => setChatOpen(true)}
          className="absolute right-4 bottom-4 flex h-12 w-12 items-center justify-center rounded-full bg-sage-700 text-white shadow-lg transition-colors hover:bg-sage-800"
        >
          <MessageCircleMore className="h-5 w-5" />
        </button>
      )}

      {/* AI 对话侧栏 */}
      {chatOpen && (
        <aside className="absolute top-0 right-0 bottom-0 flex w-full max-w-sm flex-col border-l border-cream-200 bg-white/95 shadow-2xl backdrop-blur">
          <div className="flex items-center justify-between border-b border-cream-200 px-4 py-3">
            <div className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-sage-50 text-sage-700">
                <Bot className="h-4 w-4" />
              </span>
              <div>
                <h2 className="text-sm font-semibold text-stone-800">AI 布局助手</h2>
                <p className="text-[11px] text-stone-400">用对话调整当前空间</p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setChatOpen(false)}
              className="flex h-8 w-8 items-center justify-center rounded-full text-stone-400 hover:bg-cream-100 hover:text-stone-700"
            >
              <X className="h-4 w-4" />
            </button>
          </div>

          <div ref={chatListRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4">
            {messages.length === 0 && (
              <div className="rounded-xl bg-cream-50 px-3 py-3 text-xs leading-relaxed text-stone-500">
                试试对我说：
                <br />· “加一把餐椅”
                <br />· “把沙发向左移 30 厘米”
                <br />· “床两侧加两个床头柜”
              </div>
            )}
            {messages.map((message, index) => (
              <div
                key={index}
                className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
                    message.role === "user"
                      ? "bg-sage-700 text-white"
                      : "bg-cream-100 text-stone-700"
                  }`}
                >
                  {message.content}
                </div>
              </div>
            ))}
            {sending && (
              <div className="flex justify-start">
                <div className="flex items-center gap-2 rounded-2xl bg-cream-100 px-3.5 py-2.5 text-sm text-stone-500">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  正在理解指令…
                </div>
              </div>
            )}
          </div>

          <form
            className="flex gap-2 border-t border-cream-200 p-3"
            onSubmit={(event) => {
              event.preventDefault();
              void handleSend();
            }}
          >
            <input
              value={input}
              onChange={(event) => setInput(event.target.value)}
              maxLength={1000}
              disabled={sending}
              placeholder="描述你想怎样调整布局"
              className="min-w-0 flex-1 rounded-xl border border-cream-300 bg-white px-3.5 py-2.5 text-sm text-stone-700 outline-none placeholder:text-stone-300 focus:border-sage-500 focus:ring-2 focus:ring-sage-100 disabled:bg-cream-50"
            />
            <button
              type="submit"
              disabled={sending || input.trim().length < 2}
              className="inline-flex items-center justify-center gap-1.5 rounded-xl bg-sage-700 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-sage-800 disabled:cursor-not-allowed disabled:opacity-45"
            >
              <Send className="h-4 w-4" />
              发送
            </button>
          </form>
        </aside>
      )}

      {loading && (
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="flex items-center gap-2 rounded-2xl bg-white/90 px-5 py-3 text-sm text-stone-600 shadow-lg">
            <Loader2 className="h-4 w-4 animate-spin text-sage-700" />
            正在加载家具模型…
          </div>
        </div>
      )}

      {catalogError && !loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-stone-900/25 px-4 backdrop-blur-sm">
          <div className="max-w-md rounded-2xl bg-white p-6 text-center shadow-2xl">
            <h2 className="text-base font-semibold text-stone-800">
              家具模型加载失败
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-stone-500">
              {catalogError}
            </p>
            <button
              type="button"
              onClick={() => void loadCatalog()}
              className="mt-4 rounded-xl bg-sage-700 px-4 py-2 text-sm font-medium text-white hover:bg-sage-800"
            >
              重新加载
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
