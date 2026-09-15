import { http } from "./client";
import {
  PageSchema,
  LlmConfigOut,
  LlmConfigTestOut,
  LlmLogOut,
  LlmUsageBucket,
  type LlmConfig,
  type LlmConfigCreateInput,
  type LlmConfigTestInInput,
  type LlmConfigTestResult,
  type LlmConfigUpdateInput,
  type LlmLog,
  type LlmUsageBucketT,
  type Page,
} from "./types";
import { z } from "zod";

// Configs
export type LlmConfigListQuery = { page: number; size: number; label?: string };

export async function listLlmConfigs(q: LlmConfigListQuery): Promise<Page<LlmConfig>> {
  const { data } = await http.get("/llm-configs", { params: q });
  return PageSchema(LlmConfigOut).parse(data);
}

export async function createLlmConfig(input: LlmConfigCreateInput): Promise<LlmConfig> {
  const { data } = await http.post("/llm-configs", input);
  return LlmConfigOut.parse(data);
}

export async function updateLlmConfig(
  id: string,
  input: LlmConfigUpdateInput,
): Promise<LlmConfig> {
  const payload: Record<string, unknown> = { ...input };
  if (payload.api_key === "") delete payload.api_key;
  const { data } = await http.patch(`/llm-configs/${id}`, payload);
  return LlmConfigOut.parse(data);
}

export async function deleteLlmConfig(id: string): Promise<void> {
  await http.delete(`/llm-configs/${id}`);
}

export async function activateLlmConfig(id: string): Promise<LlmConfig> {
  const { data } = await http.post(`/llm-configs/${id}/activate`);
  return LlmConfigOut.parse(data);
}

export async function activateLlmConfigCaptcha(id: string): Promise<LlmConfig> {
  const { data } = await http.post(`/llm-configs/${id}/activate-captcha`);
  return LlmConfigOut.parse(data);
}

export async function activateLlmConfigChatbot(id: string): Promise<LlmConfig> {
  const { data } = await http.post(`/llm-configs/${id}/activate-chatbot`);
  return LlmConfigOut.parse(data);
}

export async function activateLlmConfigLoopAgent(id: string): Promise<LlmConfig> {
  const { data } = await http.post(`/llm-configs/${id}/activate-loop-agent`);
  return LlmConfigOut.parse(data);
}

export async function activateLlmConfigLoopReviewer(id: string): Promise<LlmConfig> {
  const { data } = await http.post(`/llm-configs/${id}/activate-loop-reviewer`);
  return LlmConfigOut.parse(data);
}

export async function revealLlmConfigKey(id: string): Promise<{ api_key: string }> {
  const { data } = await http.get(`/llm-configs/${id}/reveal`);
  return z.object({ api_key: z.string() }).parse(data);
}

export async function testLlmConnection(
  input: LlmConfigTestInInput,
): Promise<LlmConfigTestResult> {
  const { data } = await http.post("/llm-configs/test", input);
  return LlmConfigTestOut.parse(data);
}

// Logs
export type LlmLogQuery = {
  page: number;
  size: number;
  source?: string;
  success?: boolean;
  // Splits the "fail" bucket. Backend implicitly constrains to failed
  // merge_patient_data rows when set, so combine with success=false.
  retry_status?: "retried_ok" | "not_retried";
  llm_config_id?: string;
  puskesmas_id?: string;
  since?: string;
};

export async function listLlmLogs(q: LlmLogQuery): Promise<Page<LlmLog>> {
  const { data } = await http.get("/llm-logs", { params: q });
  return PageSchema(LlmLogOut).parse(data);
}

export type LlmLogRetryMergeBulkResult = {
  triggered: number;
  skipped: number;
  skipped_reasons: string[];
  job_ids: string[];
};

const LlmLogRetryMergeBulkResultSchema = z.object({
  triggered: z.number(),
  skipped: z.number(),
  skipped_reasons: z.array(z.string()),
  job_ids: z.array(z.string()),
});

export async function retryMergeBulk(
  logIds: string[],
): Promise<LlmLogRetryMergeBulkResult> {
  const { data } = await http.post("/llm-logs/retry-merge-bulk", {
    log_ids: logIds,
  });
  return LlmLogRetryMergeBulkResultSchema.parse(data);
}

export type LlmUsageQuery = {
  group_by?: "day" | "month";
  since?: string;
  until?: string;
  source?: string;
  llm_config_id?: string;
};

export async function llmUsage(q: LlmUsageQuery): Promise<LlmUsageBucketT[]> {
  const { data } = await http.get("/llm-logs/usage", { params: q });
  return z.array(LlmUsageBucket).parse(data);
}
