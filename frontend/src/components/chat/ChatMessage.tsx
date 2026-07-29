import { motion } from "framer-motion";
import { Sparkles, User } from "lucide-react";
import type { ChatMessage as ChatMessageType } from "@/types/chat";

export default function ChatMessage({ message }: { message: ChatMessageType }) {
  const isAi = message.role === "ai";
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={`flex gap-3 ${isAi ? "" : "flex-row-reverse"}`}
    >
      <span
        className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl ${
          isAi ? "bg-sage-600 text-white" : "bg-cream-200 text-stone-500"
        }`}
      >
        {isAi ? <Sparkles className="h-4.5 w-4.5" /> : <User className="h-4.5 w-4.5" />}
      </span>
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed sm:max-w-[70%] ${
          isAi
            ? "rounded-tl-md bg-white text-stone-700 shadow-card"
            : "rounded-tr-md bg-sage-600 text-white"
        }`}
      >
        {message.content}
      </div>
    </motion.div>
  );
}
