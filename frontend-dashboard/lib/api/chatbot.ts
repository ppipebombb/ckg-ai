import { z } from "zod";
import { http } from "./client";

// The dashboard explainer chatbot. Stateless: history rides in the request and
// the backend answers only from versioned markdown — no patient data is sent.

export const ChatRole = z.enum(["user", "assistant"]);
export type ChatRole = z.infer<typeof ChatRole>;

export const ChatMessage = z.object({
  role: ChatRole,
  content: z.string(),
});
export type ChatMessage = z.infer<typeof ChatMessage>;

// Page key the backend maps to a knowledge-pack set (manifest.json).
export type ChatPage =
  | "dashboard"
  | "dashboard-dm"
  | "patients"
  | "school-patients"
  | "hipertensi-report"
  | "gap-tatalaksana"
  | "dm-report"
  | "lipid-report"
  | "obesitas-report"
  | "bayi-kuning-ikterus"
  | "bayi-kuning-ikterus-berat"
  | "common";

export const ChatRequest = z.object({
  message: z.string(),
  page: z.enum([
    "dashboard",
    "dashboard-dm",
    "patients",
    "school-patients",
    "hipertensi-report",
    "gap-tatalaksana",
    "dm-report",
    "lipid-report",
    "obesitas-report",
    "bayi-kuning-ikterus",
    "bayi-kuning-ikterus-berat",
    "common",
  ]),
  history: z.array(ChatMessage),
});
export type ChatRequestInput = z.infer<typeof ChatRequest>;

export const ChatResponse = z.object({ answer: z.string() });
export type ChatResponseT = z.infer<typeof ChatResponse>;

export async function postChatMessage(
  body: ChatRequestInput,
): Promise<ChatResponseT> {
  const { data } = await http.post("/chatbot/messages", body);
  return ChatResponse.parse(data);
}
