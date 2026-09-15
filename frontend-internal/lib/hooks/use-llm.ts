"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  activateLlmConfig,
  activateLlmConfigCaptcha,
  activateLlmConfigChatbot,
  activateLlmConfigLoopAgent,
  activateLlmConfigLoopReviewer,
  createLlmConfig,
  deleteLlmConfig,
  listLlmConfigs,
  listLlmLogs,
  llmUsage,
  retryMergeBulk,
  revealLlmConfigKey,
  testLlmConnection,
  updateLlmConfig,
  type LlmConfigListQuery,
  type LlmLogQuery,
  type LlmUsageQuery,
} from "@/lib/api/llm";
import type {
  LlmConfig,
  LlmConfigCreateInput,
  LlmConfigTestInInput,
  LlmConfigUpdateInput,
  Page,
} from "@/lib/api/types";

export const llmConfigKeys = {
  all: ["llm-configs"] as const,
  list: (q: LlmConfigListQuery) =>
    [...llmConfigKeys.all, "list", q] as const,
};

export const llmLogKeys = {
  all: ["llm-logs"] as const,
  list: (q: LlmLogQuery) => [...llmLogKeys.all, "list", q] as const,
  usage: (q: LlmUsageQuery) => [...llmLogKeys.all, "usage", q] as const,
};

// Configs
export function useLlmConfigsList(
  q: LlmConfigListQuery,
  enabled = true,
) {
  return useQuery({
    queryKey: llmConfigKeys.list(q),
    queryFn: () => listLlmConfigs(q),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useCreateLlmConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: LlmConfigCreateInput) => createLlmConfig(input),
    onSuccess: (created) => {
      qc.setQueriesData<Page<LlmConfig>>(
        { queryKey: llmConfigKeys.all },
        (old) =>
          old
            ? { ...old, items: [created, ...old.items], total: old.total + 1 }
            : old,
      );
    },
  });
}

export function useUpdateLlmConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: LlmConfigUpdateInput }) =>
      updateLlmConfig(id, input),
    onSuccess: (updated) => {
      qc.setQueriesData<Page<LlmConfig>>(
        { queryKey: llmConfigKeys.all },
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((c) =>
                  c.id === updated.id ? updated : c,
                ),
              }
            : old,
      );
    },
  });
}

export function useDeleteLlmConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteLlmConfig(id),
    onSuccess: (_v, id) => {
      qc.setQueriesData<Page<LlmConfig>>(
        { queryKey: llmConfigKeys.all },
        (old) =>
          old
            ? {
                ...old,
                items: old.items.filter((c) => c.id !== id),
                total: Math.max(0, old.total - 1),
              }
            : old,
      );
    },
  });
}

export function useActivateLlmConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => activateLlmConfig(id),
    onSuccess: (activated) => {
      qc.setQueriesData<Page<LlmConfig>>(
        { queryKey: llmConfigKeys.all },
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((c) => ({
                  ...c,
                  is_active: c.id === activated.id,
                })),
              }
            : old,
      );
    },
  });
}

export function useActivateCaptchaLlmConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => activateLlmConfigCaptcha(id),
    onSuccess: (activated) => {
      qc.setQueriesData<Page<LlmConfig>>(
        { queryKey: llmConfigKeys.all },
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((c) => ({
                  ...c,
                  is_active_captcha: c.id === activated.id,
                })),
              }
            : old,
      );
    },
  });
}

export function useActivateChatbotLlmConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => activateLlmConfigChatbot(id),
    onSuccess: (activated) => {
      qc.setQueriesData<Page<LlmConfig>>(
        { queryKey: llmConfigKeys.all },
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((c) => ({
                  ...c,
                  is_active_chatbot: c.id === activated.id,
                })),
              }
            : old,
      );
    },
  });
}

export function useActivateLoopAgentLlmConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => activateLlmConfigLoopAgent(id),
    onSuccess: (activated) => {
      qc.setQueriesData<Page<LlmConfig>>(
        { queryKey: llmConfigKeys.all },
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((c) => ({
                  ...c,
                  is_active_loop_agent: c.id === activated.id,
                })),
              }
            : old,
      );
    },
  });
}

export function useActivateLoopReviewerLlmConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => activateLlmConfigLoopReviewer(id),
    onSuccess: (activated) => {
      qc.setQueriesData<Page<LlmConfig>>(
        { queryKey: llmConfigKeys.all },
        (old) =>
          old
            ? {
                ...old,
                items: old.items.map((c) => ({
                  ...c,
                  is_active_loop_reviewer: c.id === activated.id,
                })),
              }
            : old,
      );
    },
  });
}

export function useRevealLlmConfigKey() {
  return useMutation({ mutationFn: (id: string) => revealLlmConfigKey(id) });
}

export function useTestLlmConnection() {
  return useMutation({
    mutationFn: (input: LlmConfigTestInInput) => testLlmConnection(input),
  });
}

// Logs
export function useLlmLogs(q: LlmLogQuery, enabled = true) {
  return useQuery({
    queryKey: llmLogKeys.list(q),
    queryFn: () => listLlmLogs(q),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useLlmUsage(q: LlmUsageQuery, enabled = true) {
  return useQuery({
    queryKey: llmLogKeys.usage(q),
    queryFn: () => llmUsage(q),
    enabled,
  });
}

export function useRetryMergeBulk() {
  return useMutation({ mutationFn: (logIds: string[]) => retryMergeBulk(logIds) });
}
