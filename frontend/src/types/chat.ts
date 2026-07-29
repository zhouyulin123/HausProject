export type ChatRole = "ai" | "user";

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
}
