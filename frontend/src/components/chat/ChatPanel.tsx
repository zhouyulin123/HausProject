import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Send, Sparkles } from "lucide-react";
import type { ChatMessage as ChatMessageType } from "@/types/chat";
import { quickCommands, quickReplies } from "@/data/mockChat";
import {
  sendAgentTurn,
  sendChatMessage,
  type AgentActiveMode,
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
  initialMessages?: ChatMessageType[];
  pendingQuestions?: AgentPendingQuestion[];
  onMessagesChange?: (messages: ChatMessageType[]) => void;
  onAgentResponse?: (response: AgentTurnResponse) => void;
  onGenerate?: () => void;
  workspace?: boolean;
}

export default function ChatPanel({
  projectId,
  activeMode,
  activeRoomId = null,
  sceneId = null,
  baseSceneVersion = null,
  initialMessages,
  pendingQuestions = [],
  onMessagesChange,
  onAgentResponse,
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
  const scrollRef = useRef<HTMLDivElement>(null);

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

  const send = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    setInput("");
    const userMessage: ChatMessageType = {
      id: `u-${Date.now()}`,
      role: "user",
      content: trimmed,
    };
    const nextWithUser = [...messages, userMessage];
    setMessages(nextWithUser);
    onMessagesChange?.(nextWithUser);
    setLoading(true);
    setSendError("");
    try {
      let reply: string;
      if (projectId && activeMode) {
        const response = await sendAgentTurn(projectId, {
          client_turn_id:
            typeof crypto !== "undefined" && "randomUUID" in crypto
              ? crypto.randomUUID()
              : `turn-${projectId}-${Date.now()}`,
          message: trimmed,
          active_mode: activeMode,
          active_room_id: activeRoomId,
          ...agentTurnSceneContext(sceneId, baseSceneVersion),
        });
        reply = response.reply;
        onAgentResponse?.(response);
      } else {
        reply = await sendChatMessage(trimmed);
      }
      const nextWithReply = [
        ...nextWithUser,
        { id: `a-${Date.now()}`, role: "ai" as const, content: reply },
      ];
      setMessages(nextWithReply);
      onMessagesChange?.(nextWithReply);
    } catch {
      setSendError(
        workspace
          ? "智能体服务暂未连接，本轮没有执行任何设计操作。"
          : "消息发送失败，请稍后重试。",
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      className={`flex flex-col overflow-hidden border border-[#1d241f]/15 bg-[#e2e0d7] shadow-[0_30px_80px_rgb(20_28_22/.12)] ${
        workspace
          ? "h-[680px] rounded-lg xl:h-[calc(100vh-8.5rem)] xl:min-h-[620px]"
          : "h-[calc(100vh-12rem)] min-h-[520px] rounded-[2rem]"
      }`}
    >
      {/* 消息区 */}
      <div ref={scrollRef} className="thin-scrollbar flex-1 space-y-5 overflow-y-auto p-5">
        {messages.map((message) => (
          <ChatMessage key={message.id} message={message} />
        ))}

        {showQuickReplies && !loading && (
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
              AI 正在分析你的生活方式...
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
          <p role="alert" className="ml-12 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-700">
            {sendError}
          </p>
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
      <div className="border-t border-[#1d241f]/15 bg-[#f4f1e9]/95 p-4">
        <QuickActions commands={quickCommands} onSelect={send} disabled={loading} />
        <div className="mt-3 flex items-end gap-2">
          <textarea
            rows={1}
            value={input}
            placeholder="告诉 AI 更多想法，例如「预算降低 20%」…"
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void send(input);
              }
            }}
            className="max-h-32 flex-1 resize-none rounded-xl border border-cream-300 bg-white px-4 py-2.5 text-sm text-stone-700 outline-none placeholder:text-stone-300 focus:border-sage-500 focus:ring-2 focus:ring-sage-100"
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
