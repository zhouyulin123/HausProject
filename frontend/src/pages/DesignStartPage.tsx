import { useState } from "react";
import {
  ArrowRight,
  Box,
  Loader2,
  MessageSquareText,
  ScanLine,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { createDesignTask } from "@/api/designApi";
import { DESIGN_ENTRY_MODES, designWorkspacePath } from "@/lib/designProject";
import { useDesignProjectStore } from "@/store/useDesignProjectStore";
import { useRequirementStore } from "@/store/useRequirementStore";
import { useRoomModelStore } from "@/store/useRoomModelStore";

const visuals = {
  catalog_design: {
    actionLabel: "开始搭配",
    icon: Box,
    image: "/case_image/modern-minimal-1.webp",
    accent: "#d5ff67",
  },
  custom_furniture: {
    actionLabel: "开始设计家具",
    icon: MessageSquareText,
    image: "/case_image/wood-tone-2.webp",
    accent: "#f1c08b",
  },
  room_reconstruction: {
    actionLabel: "开始设计房间",
    icon: ScanLine,
    image: "/case_image/nordic-2.webp",
    accent: "#b8d8cf",
  },
} as const;

export default function DesignStartPage() {
  const navigate = useNavigate();
  const requirement = useRequirementStore((state) => state.requirement);
  const roomModel = useRoomModelStore((state) => state.roomModel);
  const registerProject = useDesignProjectStore((state) => state.registerProject);
  const projects = useDesignProjectStore((state) =>
    Object.values(state.projects).sort((a, b) => b.updatedAt.localeCompare(a.updatedAt)),
  );
  const [creatingMode, setCreatingMode] = useState<string | null>(null);
  const [createError, setCreateError] = useState("");

  const start = async (mode: (typeof DESIGN_ENTRY_MODES)[number]["id"]) => {
    if (creatingMode) return;
    setCreatingMode(mode);
    setCreateError("");
    try {
      const taskId = await createDesignTask(requirement, mode);
      registerProject(taskId, mode, { requirement, roomModel });
      navigate(designWorkspacePath(taskId));
    } catch {
      setCreateError("暂时无法开始设计，请稍后重试。");
    } finally {
      setCreatingMode(null);
    }
  };

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-[#111713] px-5 py-10 text-[#e8ebe4] sm:px-8 lg:px-12 lg:py-14">
      <div className="mx-auto max-w-[1480px]">
        <header className="grid gap-8 border-b border-white/12 pb-10 lg:grid-cols-[1fr_440px] lg:items-end">
          <div>
            <p className="font-mono text-[10px] tracking-[0.2em] text-[#d5ff67] uppercase">
              开始新的设计
            </p>
            <h1 className="mt-5 max-w-3xl font-display text-4xl leading-[1.08] font-medium !text-[#f2f0e9] sm:text-5xl">
              这次，你想设计什么？
            </h1>
          </div>
        </header>

        {createError && (
          <p role="alert" className="mt-5 border border-[#8f4938] bg-[#2b1c18] px-4 py-3 text-sm text-[#f1b59e]">
            {createError}
          </p>
        )}

        <section className="mt-8 grid gap-px overflow-hidden border border-white/12 bg-white/12 lg:grid-cols-3">
          {DESIGN_ENTRY_MODES.map((entry) => {
            const visual = visuals[entry.id];
            const Icon = visual.icon;
            const creating = creatingMode === entry.id;
            return (
              <article key={entry.id} className="group flex min-h-[470px] flex-col bg-[#161d18]">
                <div className="relative h-52 overflow-hidden bg-[#202821]">
                  <img
                    src={visual.image}
                    alt=""
                    className="h-full w-full object-cover opacity-70 saturate-[.72] transition duration-700 group-hover:scale-[1.035] group-hover:opacity-90"
                  />
                  <div className="absolute inset-0 bg-gradient-to-t from-[#161d18] via-transparent to-black/15" />
                  <span className="absolute top-5 left-5 font-mono text-xs text-white/65">{entry.index}</span>
                  <span
                    className="absolute right-5 bottom-2 flex h-11 w-11 items-center justify-center rounded-full text-[#111713]"
                    style={{ backgroundColor: visual.accent }}
                  >
                    <Icon className="h-5 w-5" />
                  </span>
                </div>
                <div className="flex flex-1 flex-col p-6 sm:p-7">
                  <p className="font-mono text-[10px] tracking-[0.16em] text-[#7f8b81] uppercase">{entry.shortTitle}</p>
                  <h2 className="mt-4 text-2xl font-medium !text-[#ecebe5]">{entry.title}</h2>
                  <p className="mt-4 text-sm leading-7 text-[#96a097]">{entry.description}</p>
                  <button
                    type="button"
                    disabled={Boolean(creatingMode)}
                    onClick={() => void start(entry.id)}
                    className="mt-auto flex min-h-11 items-center justify-between border-t border-white/12 pt-5 text-sm font-medium text-[#d9ded7] transition-colors hover:text-[#d5ff67] disabled:cursor-wait disabled:opacity-50"
                  >
                    {creating ? "正在准备…" : visual.actionLabel}
                    {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />}
                  </button>
                </div>
              </article>
            );
          })}
        </section>

        {projects.length > 0 && (
          <section className="mt-12 border-t border-white/12 pt-7">
            <div className="flex items-center justify-between gap-4">
              <h2 className="text-sm font-medium !text-[#d9ddd6]">最近的设计</h2>
              <span className="font-mono text-[10px] text-[#778278]">{projects.length} 个设计</span>
            </div>
            <div className="mt-4 divide-y divide-white/10 border-y border-white/10">
              {projects.slice(0, 4).map((project) => (
                <button
                  key={project.id}
                  type="button"
                  onClick={() => navigate(designWorkspacePath(project.id))}
                  className="flex w-full items-center gap-4 py-4 text-left transition-colors hover:text-[#d5ff67]"
                >
                  <span className="min-w-0 flex-1 truncate text-sm">{project.title}</span>
                  <span className="hidden text-xs text-[#778278] sm:block">{project.requirement.rooms.join("、") || "空间待确认"}</span>
                  <ArrowRight className="h-4 w-4 shrink-0" />
                </button>
              ))}
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
