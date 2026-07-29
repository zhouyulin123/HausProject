import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { motion } from "framer-motion";
import { Send, Sparkles } from "lucide-react";
import type { ChatMessage as ChatMessageType } from "@/types/chat";
import { initialMessages, quickCommands, quickReplies } from "@/data/mockChat";
import { sendChatMessage } from "@/api/designApi";
import ChatMessage from "./ChatMessage";
import QuickActions from "./QuickActions";
import LoadingAI from "./LoadingAI";
import Button from "@/components/common/Button";

export default function ChatPanel() {
  const navigate = useNavigate();
  const [messages, setMessages] = useState<ChatMessageType[]>(initialMessages);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const aiReplyCount = messages.filter((m) => m.role === "ai").length;
  const showQuickReplies = messages.length === 1;
  const showGenerate = aiReplyCount >= 2;

  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages, loading]);

  const send = async (text: string) => {
    const trimmed = text.trim();
    if (!trimmed || loading) return;
    setInput("");
    setMessages((prev) => [
      ...prev,
      { id: `u-${Date.now()}`, role: "user", content: trimmed },
    ]);
    setLoading(true);
    const reply = await sendChatMessage(trimmed);
    setMessages((prev) => [
      ...prev,
      { id: `a-${Date.now()}`, role: "ai", content: reply },
    ]);
    setLoading(false);
  };

  return (
    <div className="flex h-[calc(100vh-12rem)] min-h-[480px] flex-col rounded-3xl border border-cream-200 bg-cream-100/50">
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

        {showGenerate && !loading && (
          <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="flex justify-center pt-2"
          >
            <Button variant="terra" size="lg" onClick={() => navigate("/results")}>
              <Sparkles className="h-4 w-4" />
              需求确认完毕，生成我的方案
            </Button>
          </motion.div>
        )}
      </div>

      {/* 快捷指令 + 输入框 */}
      <div className="border-t border-cream-200 bg-white/70 p-4 rounded-b-3xl">
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
