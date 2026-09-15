"use client";

import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useActivateCaptchaLlmConfig, useActivateChatbotLlmConfig, useActivateLoopAgentLlmConfig, useActivateLoopReviewerLlmConfig, useActivateLlmConfig } from "@/lib/hooks/use-llm";
import { asApiError } from "@/lib/api/client";
import type { LlmConfig } from "@/lib/api/types";

type RoleRow = {
  key: string;
  label: string;
  description: string;
  held: boolean;
};

export function LlmRoleDialog({
  config,
  open,
  onOpenChange,
}: {
  config: LlmConfig | null;
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const activate = useActivateLlmConfig();
  const activateCaptcha = useActivateCaptchaLlmConfig();
  const activateChatbot = useActivateChatbotLlmConfig();
  const activateLoopAgent = useActivateLoopAgentLlmConfig();
  const activateLoopReviewer = useActivateLoopReviewerLlmConfig();

  const roles: (RoleRow & { activate: () => Promise<void>; pending: boolean })[] = config
    ? [
        {
          key: "utama",
          label: "Utama (merge)",
          description: "LLM umum — menilai konflik saat merge pasien.",
          held: config.is_active,
          activate: async () => {
            await activate.mutateAsync(config.id);
            toast.success("Diaktifkan sebagai utama");
          },
          pending: activate.isPending,
        },
        {
          key: "captcha",
          label: "Captcha",
          description: "Pemecah captcha ASIK saat scraping.",
          held: config.is_active_captcha,
          activate: async () => {
            await activateCaptcha.mutateAsync(config.id);
            toast.success("Diatur untuk captcha");
          },
          pending: activateCaptcha.isPending,
        },
        {
          key: "chatbot",
          label: "Chatbot",
          description: "Chatbot penjelasan di dashboard eksternal.",
          held: config.is_active_chatbot,
          activate: async () => {
            await activateChatbot.mutateAsync(config.id);
            toast.success("Diatur untuk chatbot");
          },
          pending: activateChatbot.isPending,
        },
        {
          key: "loop_agent",
          label: "Loop Agent",
          description: "Agen perbaik scraper EPUS (GLM-5.3-Flash).",
          held: config.is_active_loop_agent,
          activate: async () => {
            await activateLoopAgent.mutateAsync(config.id);
            toast.success("Diatur untuk loop agent");
          },
          pending: activateLoopAgent.isPending,
        },
        {
          key: "loop_reviewer",
          label: "Loop Reviewer",
          description: "Reviewer PR hasil loop agent (GLM-5.3).",
          held: config.is_active_loop_reviewer,
          activate: async () => {
            await activateLoopReviewer.mutateAsync(config.id);
            toast.success("Diatur untuk loop reviewer");
          },
          pending: activateLoopReviewer.isPending,
        },
      ]
    : [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Atur Peran LLM</DialogTitle>
          <DialogDescription>
            {config
              ? `${config.label ?? config.model} — setiap peran dipegang satu konfigurasi; mengaktifkan di sini memindahkan peran dari konfigurasi lain.`
              : undefined}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          {roles.map((role) => (
            <div
              key={role.key}
              className="flex items-center justify-between gap-3 rounded-md border border-[var(--border)] p-3"
            >
              <div className="min-w-0">
                <p className="text-sm font-medium">{role.label}</p>
                <p className="text-xs text-[var(--muted-foreground)]">
                  {role.description}
                </p>
              </div>
              {role.held ? (
                <Badge variant="success">aktif</Badge>
              ) : (
                <Button
                  variant="outline"
                  size="sm"
                  disabled={role.pending}
                  onClick={async () => {
                    try {
                      await role.activate();
                    } catch (err) {
                      toast.error(asApiError(err).message);
                    }
                  }}
                >
                  Jadikan aktif
                </Button>
              )}
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
