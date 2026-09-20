import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { RotateCcw, Send, Sparkles } from "lucide-react";
import type { ChatMessage as ChatMessageType } from "@/types/chat";
import { quickCommands, quickReplies } from "@/data/mockChat";
import {
  ApiError,
  sendAgentTurn,
  sendChatMessage,
  type AgentActiveMode,
  type AgentTurnRequest,
  type AgentTurnResponse,
} from "@/api/designApi";
import { buildOpeningMessage } from "@/lib/openingMessage";
import { useRequirementStore } from "@/store/useRequirementStore";
import ChatMessage from "./ChatMessage";
import QuickActions from "./QuickActions";
import LoadingAI from "./LoadingAI";
import Button from "@/components/common/Button";
import type { AgentPendingQuestion } from "@/types/agent";
import { agentTurnSceneContext } from "@/lib/sceneEditingPolicy";

interface ChatPanelProps {
  projectId?: number;
  activeMode?: AgentActiveMode;
  activeRoomId?: string | null;
  sceneId?: number | null;
  baseSceneVersion?: number | null;
  baseStateVersion?: number;
  initialMessages?: ChatMessageType[];
  pendingQuestions?: AgentPendingQuestion[];
  onMessagesChange?: (messages: ChatMessageType[]) => void;
  onAgentResponse?: (response: AgentTurnResponse) => void;
  onAgentStateConflict?: () => Promise<void> | void;
  onGenerate?: () => void;
  workspace?: boolean;
}

export interface PendingSend {
  text: string;
  clientTurnId: string;
  messagesWithUser: ChatMessageType[];
}

export class AgentStateConflictRefreshError extends Error {
  constructor() {
    super("agent_state_conflict_refresh_failed");
    this.name = "AgentStateConflictRefreshError";
  }
}

export function createPendingSend(
  text: string,
  currentMessages: ChatMessageType[],
  clientTurnId: string,
  stamp: number,
): PendingSend {
  return {
    text,
    clientTurnId,
    messagesWithUser: [
      ...currentMessages,
      { id: `u-${stamp}`, role: "user", content: text },
    ],
  };
}

export function buildWorkspaceAgentTurn(
  pending: PendingSend,
  context: {
    activeMode: AgentActiveMode;
    activeRoomId: string | null;
    sceneId: number | null;
    baseSceneVersion: number | null;
    baseStateVersion: number;
  },
): AgentTurnRequest {
  return {
    client_turn_id: pending.clientTurnId,
    message: pending.text,
    active_mode: context.activeMode,
    active_room_id: context.activeRoomId,
    base_state_version: context.baseStateVersion,
    ...agentTurnSceneContext(context.sceneId, context.baseSceneVersion),
  };
}

export function workspaceAgentSendFailure(error: unknown): {
  message: string;
  retryable: boolean;
} {
  if (error instanceof AgentStateConflictRefreshError) {
    return {
      message: "设计状态已变化，但最新状态读取失败。请刷新页面后再继续。",
      retryable: false,
    };
  }
  if (error instanceof ApiError) {
    const detail = typeof error.detail === "object" && error.detail
      ? error.detail as { code?: string; message?: string }
      : null;
    if (error.status === 409 && detail?.code === "agent_state_conflict") {
      return {
        message: "设计状态已被更新，请查看最新结果后重新发送需求。",
        retryable: false,
      };
    }
    const serverMessage = detail?.message
      ?? (typeof error.detail === "string" ? error.detail : error.message);
    return { message: serverMessage, retryable: true };
  }
  return {
    message: "智能体服务暂时不可用，本轮没有执行任何设计操作。",
    retryable: true,
  };
}

export async function recoverWorkspaceAgentConflict(
  error: unknown,
  refresh: () => Promise<void> | void,
): Promise<boolean> {
  const detail = error instanceof ApiError
    && typeof error.detail === "object"
    && error.detail
    ? error.detail as { code?: string }
    : null;
  if (!(error instanceof ApiError)
    || error.status !== 409
    || detail?.code !== "agent_state_conflict") return false;
  try {
    await refresh();
  } catch {
    throw new AgentStateConflictRefreshError();
  }
  return true;
}

export default function ChatPanel({
  projectId,
  activeMode,
  activeRoomId = null,
  sceneId = null,
  baseSceneVersion = null,
  baseStateVersion = 0,
  initialMessages,
  pendingQuestions = [],
  onMessagesChange,
  onAgentResponse,
  onAgentStateConflict,
  onGenerate,
  workspace = false,
}: ChatPanelProps = {}) {
  const navigate = useNavigate();
  const requirement = useRequirementStore((s) => s.requirement);
  const [messages, setMessages] = useState<ChatMessageType[]>(() =>
    initialMessages !== undefined
      ? initialMessages
      : [
          {
            id: "m0",
            role: "ai",
            content: buildOpeningMessage(requirement),
          },
        ],
  );
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sendError, setSendError] = useState("");
  const [failedSend, setFailedSend] = useState<PendingSend | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const sendingRef = useRef(false);

  const aiReplyCount = messages.filter((m) => m.role === "ai").length;
  const showQuickReplies = messages.length === 1;
  const showGenerate = !workspace && aiReplyCount >= 2;

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, loading]);

  useEffect(() => {
    if (initialMessages !== undefined) setMessages(initialMessages);
  }, [initialMessages]);

  const executeSend = async (pending: PendingSend) => {
    if (sendingRef.current) return;
    sendingRef.current = true;
    setLoading(true);
    setSendError("");
    try {
      let reply: string;
      if (projectId && activeMode) {
        const response = await sendAgentTurn(projectId, buildWorkspaceAgentTurn(pending, {
          activeMode,
          activeRoomId,
          sceneId,
          baseSceneVersion,
          baseStateVersion,
        }));
        reply = response.reply;
        onAgentResponse?.(response);
      } else {
        reply = await sendChatMessage(pending.text);
      }
      const nextWithReply = [
        ...pending.messagesWithUser,
        { id: `a-${Date.now()}`, role: "ai" as const, content: reply },
      ];
      setMessages(nextWithReply);
      onMessagesChange?.(nextWithReply);
      setFailedSend(null);
    } catch (cause) {
      let failureCause = cause;
      if (workspace) {
        try {
          await recoverWorkspaceAgentConflict(
            cause,
            async () => {
              if (!onAgentStateConflict) throw new AgentStateConflictRefreshError();
              await onAgentStateConflict();
            },
          );
        } catch (recoveryError) {
          failureCause = recoveryError;
        }
      }
      const failure = workspace
        ? workspaceAgentSendFailure(failureCause)
        : { message: "消息发送失败，请稍后重试。", retryable: true };
      setFailedSend(failure.retryable ? pending : null);
      setSendError(failure.message);
    } finally {
      sendingRef.current = false;
      setLoading(false);
    }
  };

  const send = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    setInput("");
    setFailedSend(null);
    const stamp = Date.now();
    const pending = createPendingSend(
      trimmed,
      messages,
      (
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `turn-${projectId ?? "chat"}-${stamp}`
      ),
      stamp,
    );
    setMessages(pending.messagesWithUser);
    onMessagesChange?.(pending.messagesWithUser);
    await executeSend(pending);
  };

  return (
    <div
      className={`flex flex-col overflow-hidden border border-[#1d241f]/15 bg-[#e2e0d7] shadow-[0_30px_80px_rgb(20_28_22/.12)] ${
        workspace
          ? "h-[calc(100dvh-16rem)] min-h-[360px] !border-0 !bg-[#f8faf9] !shadow-none lg:h-auto lg:min-h-0 lg:flex-1"
          : "h-[calc(100vh-12rem)] min-h-[520px] rounded-[2rem]"
      }`}
    >
      {/* 消息区 */}
      <div ref={scrollRef} className="thin-scrollbar flex-1 space-y-5 overflow-y-auto p-5">
        {messages.map((message) => (
          <ChatMessage key={message.id} message={message} />
        ))}

        {showQuickReplies && !loading && activeMode !== "custom_furniture" && (
          <div className="flex flex-wrap gap-2 pl-12">
            {quickReplies.map((reply) => (
              <button
                key={reply}
                type="button"
                onClick={() => send(reply)}
                className="rounded-full border border-sage-300 bg-white px-3.5 py-2 text-xs font-medium text-sage-700 transition-all hover:bg-sage-50"
              >
                {reply}
              </button>
            ))}
          </div>
        )}

        {loading && (
          <div className="flex items-center gap-3 pl-12">
            <LoadingAI compact />
            <span className="text-xs text-stone-400">
              {activeMode === "custom_furniture" ? "正在设计家具…" : "AI 正在分析你的生活方式..."}
            </span>
          </div>
        )}

        {workspace && pendingQuestions.length > 0 && !loading && (
          <div className="ml-12 space-y-2 border-l-2 border-sage-500 pl-3">
            {pendingQuestions.map((question) => (
              <div key={`${question.field}-${question.prompt}`}>
                <p className="text-xs font-medium text-stone-700">{question.prompt}</p>
                <p className="mt-0.5 text-[10px] leading-4 text-stone-400">{question.reason}</p>
              </div>
            ))}
          </div>
        )}

        {sendError && (
          <div role="alert" className="ml-12 flex items-center justify-between gap-3 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-700">
            <span>{sendError}</span>
            {failedSend && (
              <button
                type="button"
                disabled={loading}
                onClick={() => void executeSend(failedSend)}
                className="inline-flex min-h-8 shrink-0 items-center gap-1.5 px-2 font-semibold hover:bg-red-100 disabled:opacity-50"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                重试本轮
              </button>
            )}
          </div>
        )}

        {showGenerate && !loading && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="flex justify-center pt-2"
          >
            <Button
              variant="terra"
              size="lg"
              onClick={() => (onGenerate ? onGenerate() : navigate("/results"))}
            >
              <Sparkles className="h-4 w-4" />
              需求确认完毕，生成我的方案
            </Button>
          </motion.div>
        )}
      </div>

      {/* 快捷指令 + 输入框 */}
      <div className={`shrink-0 border-t border-[#1d241f]/15 p-4 ${activeMode === "custom_furniture" ? "bg-white" : "bg-[#f4f1e9]/95"}`}>
        {activeMode === "custom_furniture" ? (
          <div className="flex flex-wrap gap-2">
            {["调整尺寸", "修改材质", "修改造型"].map((label) => <button key={label} type="button" disabled={loading}
              onClick={() => { setInput(`${label}：`); scrollRef.current?.parentElement?.querySelector('textarea')?.focus(); }}
              className="min-h-8 rounded border border-[#d5dbd7] px-2 text-xs text-[#53655a] hover:bg-[#e8eeea]">{label}</button>)}
          </div>
        ) : <QuickActions commands={quickCommands} onSelect={send} disabled={loading} />}
        <div className="mt-3 flex items-end gap-2">
          <textarea
            rows={workspace ? 3 : 1}
            value={input}
            aria-label="设计需求"
            placeholder={activeMode === "custom_furniture" ? "描述家具，或继续修改当前作品…" : "告诉 AI 更多想法，例如「预算降低 20%」…"}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void send(input);
              }
            }}
            className="min-w-0 max-h-32 flex-1 resize-none rounded border border-[#d5dbd7] bg-white px-3 py-2.5 text-sm text-stone-700 outline-none placeholder:text-stone-400 focus:border-sage-500 focus:ring-2 focus:ring-sage-100"
          />
          <Button onClick={() => void send(input)} disabled={!input.trim() || loading}>
            <Send className="h-4 w-4" />
            发送
          </Button>
        </div>
      </div>
    </div>
  );
}
