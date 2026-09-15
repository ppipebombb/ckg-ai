"use client";

import { useMemo, useState } from "react";
import { Eye, Pencil, Plus, Search, Settings2, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Pagination } from "@/components/common/pagination";
import { ErrorState } from "@/components/common/error-state";
import { EmptyState } from "@/components/common/empty-state";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import { LlmConfigFormDialog } from "@/components/llm/llm-config-form-dialog";
import { LlmRoleDialog } from "@/components/llm/llm-role-dialog";
import {
  useDeleteLlmConfig,
  useLlmConfigsList,
  useRevealLlmConfigKey,
} from "@/lib/hooks/use-llm";
import { asApiError } from "@/lib/api/client";
import type { LlmConfig } from "@/lib/api/types";
import { useLlmConfigsListStore } from "@/lib/stores/llm-configs-list-store";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";

function formatUsd(v: string | number | null | undefined): string {
  if (v == null) return "—";
  const n = Number(v);
  if (isNaN(n)) return "—";
  return `$${n.toFixed(2)}`;
}

async function copyToClipboard(text: string) {
  if (!text) throw new Error("API key kosong");

  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return;
    } catch {
      // Fall back for browsers that expose Clipboard API but deny the write.
    }
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.left = "0";
  textarea.style.opacity = "0";
  textarea.style.position = "fixed";
  textarea.style.top = "0";

  document.body.appendChild(textarea);
  textarea.focus();
  textarea.select();

  try {
    if (!document.execCommand("copy")) {
      throw new Error("Tidak bisa menyalin API key ke clipboard");
    }
  } finally {
    textarea.remove();
  }
}

function errorMessage(err: unknown, fallback: string) {
  const apiError = asApiError(err);
  if (apiError.status !== 0 || apiError.message !== "Unknown error") {
    return apiError.message;
  }
  return err instanceof Error && err.message ? err.message : fallback;
}

export default function LlmConfigsPage() {
  const page = useLlmConfigsListStore((s) => s.page);
  const label = useLlmConfigsListStore((s) => s.label);
  const setPage = useLlmConfigsListStore((s) => s.setPage);
  const setLabel = useLlmConfigsListStore((s) => s.setLabel);

  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<LlmConfig | null>(null);
  const [deleting, setDeleting] = useState<LlmConfig | null>(null);
  const [roleConfig, setRoleConfig] = useState<LlmConfig | null>(null);

  const debouncedLabel = useDebouncedValue(label);
  const query = useMemo(
    () => ({ page, size: 20, label: debouncedLabel.trim() || undefined }),
    [page, debouncedLabel],
  );
  const list = useLlmConfigsList(query);
  const reveal = useRevealLlmConfigKey();
  const del = useDeleteLlmConfig();






  const handleReveal = async (id: string) => {
    try {
      const data = await reveal.mutateAsync(id);
      await copyToClipboard(data.api_key);
      toast.success("API key disalin ke clipboard");
    } catch (err) {
      toast.error(errorMessage(err, "Tidak bisa menyalin API key ke clipboard"));
    }
  };

  const handleDelete = async () => {
    if (!deleting) return;
    try {
      await del.mutateAsync(deleting.id);
      toast.success("Konfigurasi dihapus");
      setDeleting(null);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Konfigurasi LLM"
        description="Provider, model, harga. Satu konfigurasi aktif untuk penggunaan LLM umum; konfigurasi kedua opsional bisa diatur untuk pemecah captcha."
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            Konfigurasi Baru
          </Button>
        }
      />

      {list.error && <ErrorState error={list.error} />}

      <div className="relative max-w-sm">
        <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-[var(--muted-foreground)]" />
        <Input
          placeholder="Cari berdasarkan label…"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          className="pl-8"
        />
      </div>

      <div className="rounded-lg border border-[var(--border)]">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Label / Model</TableHead>
              <TableHead>Provider</TableHead>
              <TableHead>Harga /1M</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="w-[150px]">Aksi</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {list.data?.items.map((c) => (
              <TableRow key={c.id}>
                <TableCell>
                  <div className="font-medium">{c.label ?? c.model}</div>
                  <div className="text-xs text-[var(--muted-foreground)]">
                    {c.model}
                  </div>
                </TableCell>
                <TableCell>{c.provider}</TableCell>
                <TableCell className="text-xs text-[var(--muted-foreground)]">
                  masuk: {formatUsd(c.input_price_per_1m)} • keluar: {formatUsd(c.output_price_per_1m)}
                </TableCell>
                <TableCell>
                  <div className="flex flex-wrap items-center gap-1">
                    {c.is_active && <Badge variant="success">aktif</Badge>}
                    {/* "nonaktif" = used by NOTHING: no merge role, no specialist
                        role. A config holding any role shows only its badges. */}
                    {!(
                      c.is_active ||
                      c.is_active_captcha ||
                      c.is_active_chatbot ||
                      c.is_active_loop_agent ||
                      c.is_active_loop_reviewer
                    ) && <Badge variant="outline">nonaktif</Badge>}
                    {c.is_active_captcha && <Badge variant="success">captcha</Badge>}
                    {c.is_active_chatbot && <Badge variant="success">chatbot</Badge>}
                    {c.is_active_loop_agent && <Badge variant="success">loop agent</Badge>}
                    {c.is_active_loop_reviewer && <Badge variant="success">loop reviewer</Badge>}
                  </div>
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setRoleConfig(c)}
                    >
                      <Settings2 className="h-4 w-4" />
                      Atur
                    </Button>

                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => handleReveal(c.id)}
                      title="Salin API key"
                      className="h-8 w-8"
                    >
                      <Eye className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setEditing(c)}
                      className="h-8 w-8"
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setDeleting(c)}
                      className="h-8 w-8 text-[var(--destructive)]"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {list.data && list.data.items.length === 0 && (
          <div className="p-6">
            <EmptyState
              title="Belum ada konfigurasi LLM"
              description="Tambahkan konfigurasi OpenAI-compatible pertamamu untuk mengaktifkan scraping."
            />
          </div>
        )}
      </div>

      {list.data && (
        <Pagination
          page={list.data.page}
          pages={list.data.pages}
          total={list.data.total}
          onPageChange={setPage}
        />
      )}

      <LlmConfigFormDialog
        open={createOpen || !!editing}
        onOpenChange={(v) => {
          if (!v) {
            setCreateOpen(false);
            setEditing(null);
          }
        }}
        config={editing ?? undefined}
      />

      <LlmRoleDialog
        config={roleConfig}
        open={!!roleConfig}
        onOpenChange={(v) => !v && setRoleConfig(null)}
      />

      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(v) => !v && setDeleting(null)}
        title="Hapus konfigurasi LLM?"
        description={
          deleting ? `"${deleting.label ?? deleting.model}" akan dihapus.` : undefined
        }
        confirmLabel="Hapus"
        destructive
        loading={del.isPending}
        onConfirm={handleDelete}
      />
    </div>
  );
}
