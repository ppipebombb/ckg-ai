"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { z } from "zod";
import {
  LlmConfigCreate,
  type LlmConfig,
  type LlmConfigTestResult,
  type ReasoningEffortT,
} from "@/lib/api/types";
import {
  useCreateLlmConfig,
  useTestLlmConnection,
  useUpdateLlmConfig,
} from "@/lib/hooks/use-llm";
import { applyApiErrorToForm } from "@/lib/api/form-errors";
import { asApiError } from "@/lib/api/client";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// Radix SelectItem cannot use an empty-string value; this sentinel maps to
// "" (= use provider default) in the form/payload.
const RE_DEFAULT = "__default__";
// "Custom…" reveals a free-text input so any provider-specific value can be set.
const RE_CUSTOM = "__custom__";
// Known presets across providers (passed through verbatim). Anything not here
// (or an unusual case) goes through the Custom free-text input.
const RE_PRESETS = ["none", "minimal", "low", "medium", "high", "xhigh", "max"];

const FormSchema = LlmConfigCreate.extend({
  api_key: z.string().optional(),
});
type FormValues = z.infer<typeof FormSchema>;

export function LlmConfigFormDialog({
  open,
  onOpenChange,
  config,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  config?: LlmConfig;
}) {
  const isEdit = !!config;
  const create = useCreateLlmConfig();
  const update = useUpdateLlmConfig();
  const test = useTestLlmConnection();
  const [testResult, setTestResult] = useState<LlmConfigTestResult | null>(null);
  // True when the reasoning_effort value isn't one of the presets — shows the
  // free-text input instead of forcing it onto the dropdown.
  const [reasoningCustom, setReasoningCustom] = useState(false);

  const form = useForm<FormValues>({
    resolver: zodResolver(FormSchema),
    defaultValues: {
      provider: "openai",
      model: "",
      base_url: "https://api.openai.com/v1",
      api_key: "",
      is_active: false,
      is_active_captcha: false,
      label: "",
      reasoning_effort: "",
      route_order: "",
      input_price_per_1m: "",
      output_price_per_1m: "",
    },
  });

  useEffect(() => {
    if (open) {
      setTestResult(null);
      const re = config?.reasoning_effort ?? "";
      setReasoningCustom(re !== "" && !RE_PRESETS.includes(re));
      form.reset({
        provider: config?.provider ?? "openai",
        model: config?.model ?? "",
        base_url: config?.base_url ?? "https://api.openai.com/v1",
        api_key: "",
        is_active: config?.is_active ?? false,
        is_active_captcha: config?.is_active_captcha ?? false,
        label: config?.label ?? "",
        reasoning_effort: (config?.reasoning_effort ?? "") as ReasoningEffortT,
        route_order: config?.route_order ?? "",
        input_price_per_1m:
          config?.input_price_per_1m == null ? "" : Number(config.input_price_per_1m).toFixed(2),
        output_price_per_1m:
          config?.output_price_per_1m == null ? "" : Number(config.output_price_per_1m).toFixed(2),
      });
    }
  }, [open, config, form]);

  const onTest = async () => {
    setTestResult(null);
    const v = form.getValues();
    if (!v.model || !v.base_url) {
      toast.error("Model dan Base URL wajib diisi untuk tes");
      return;
    }
    const apiKey = (v.api_key ?? "").trim();
    if (!apiKey && !config?.id) {
      form.setError("api_key", { message: "Masukkan API key untuk tes" });
      return;
    }
    try {
      const res = await test.mutateAsync({
        provider: v.provider,
        model: v.model,
        base_url: v.base_url,
        reasoning_effort: (v.reasoning_effort ?? "") as ReasoningEffortT,
        route_order: (v.route_order ?? "") || undefined,
        api_key: apiKey || undefined,
        config_id: apiKey ? undefined : config?.id,
      });
      setTestResult(res);
    } catch (err) {
      setTestResult({ ok: false, model: v.model, error: asApiError(err).message });
    }
  };

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      const payload = {
        ...values,
        label: values.label || null,
        input_price_per_1m: values.input_price_per_1m === "" ? null : values.input_price_per_1m,
        output_price_per_1m: values.output_price_per_1m === "" ? null : values.output_price_per_1m,
      };
      if (isEdit) {
        await update.mutateAsync({
          id: config!.id,
          input: {
            provider: payload.provider,
            model: payload.model,
            base_url: payload.base_url,
            label: payload.label,
            reasoning_effort: payload.reasoning_effort ?? "",
            route_order: payload.route_order ?? "",
            input_price_per_1m: payload.input_price_per_1m,
            output_price_per_1m: payload.output_price_per_1m,
            api_key: payload.api_key || undefined,
          },
        });
        toast.success("Konfigurasi diperbarui");
      } else {
        if (!payload.api_key) {
          form.setError("api_key", { message: "API key wajib diisi" });
          return;
        }
        await create.mutateAsync({ ...payload, api_key: payload.api_key });
        toast.success("Konfigurasi dibuat");
      }
      onOpenChange(false);
    } catch (err) {
      applyApiErrorToForm(err, form.setError, ["provider", "model", "base_url", "api_key", "label", "reasoning_effort", "route_order", "input_price_per_1m", "output_price_per_1m", "is_active", "is_active_captcha"] as const);
    }
  });

  const submitting = create.isPending || update.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit Konfigurasi LLM" : "Konfigurasi LLM Baru"}</DialogTitle>
          <DialogDescription>
            {isEdit ? "Perbarui provider, model, key, atau harga." : "Tambahkan konfigurasi provider LLM baru."}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="grid grid-cols-2 gap-4">
          <div className="col-span-2 space-y-2">
            <Label htmlFor="label">Label</Label>
            <Input id="label" placeholder="mis. GPT-4o (Prod)" {...form.register("label")} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="provider">Provider</Label>
            <Input id="provider" {...form.register("provider")} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="model">Model</Label>
            <Input id="model" placeholder="gpt-4o" {...form.register("model")} />
          </div>
          <div className="col-span-2 space-y-2">
            <Label htmlFor="base_url">Base URL</Label>
            <Input id="base_url" {...form.register("base_url")} />
          </div>
          <div className="col-span-2 space-y-2">
            <Label htmlFor="api_key">
              API Key {isEdit && <span className="text-[var(--muted-foreground)]">(kosongkan untuk tetap)</span>}
            </Label>
            <Input id="api_key" type="password" autoComplete="off" {...form.register("api_key")} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="ip">Harga input / 1M token</Label>
            <div className="relative">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-[var(--muted-foreground)]">$</span>
              <Input id="ip" inputMode="decimal" step="0.01" min="0" className="pl-6" {...form.register("input_price_per_1m")} />
            </div>
            {form.formState.errors.input_price_per_1m && (
              <p className="text-xs text-[var(--destructive)]">{form.formState.errors.input_price_per_1m.message}</p>
            )}
          </div>
          <div className="space-y-2">
            <Label htmlFor="op">Harga output / 1M token</Label>
            <div className="relative">
              <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-[var(--muted-foreground)]">$</span>
              <Input id="op" inputMode="decimal" step="0.01" min="0" className="pl-6" {...form.register("output_price_per_1m")} />
            </div>
            {form.formState.errors.output_price_per_1m && (
              <p className="text-xs text-[var(--destructive)]">{form.formState.errors.output_price_per_1m.message}</p>
            )}
          </div>
          <div className="col-span-2 space-y-2">
            <Label>Reasoning effort</Label>
            <Select
              value={
                reasoningCustom
                  ? RE_CUSTOM
                  : form.watch("reasoning_effort") || RE_DEFAULT
              }
              onValueChange={(v) => {
                if (v === RE_CUSTOM) {
                  setReasoningCustom(true);
                  return;
                }
                setReasoningCustom(false);
                form.setValue(
                  "reasoning_effort",
                  (v === RE_DEFAULT ? "" : v) as ReasoningEffortT,
                  { shouldDirty: true },
                );
              }}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={RE_DEFAULT}>Default (provider yang menentukan)</SelectItem>
                <SelectItem value="none">None (matikan reasoning)</SelectItem>
                <SelectItem value="minimal">Minimal</SelectItem>
                <SelectItem value="low">Low</SelectItem>
                <SelectItem value="medium">Medium</SelectItem>
                <SelectItem value="high">High</SelectItem>
                <SelectItem value="xhigh">xHigh</SelectItem>
                <SelectItem value="max">Max</SelectItem>
                <SelectItem value={RE_CUSTOM}>Kustom…</SelectItem>
              </SelectContent>
            </Select>
            {reasoningCustom && (
              <Input
                placeholder="Nilai kustom, mis. xhigh, max, none"
                autoComplete="off"
                {...form.register("reasoning_effort")}
              />
            )}
            <p className="text-xs text-[var(--muted-foreground)]">
              Diteruskan ke provider apa adanya (OpenAI: low/medium/high/xhigh;
              DeepSeek: high/max; gpt-oss: low/medium/high). Gunakan Tes koneksi
              untuk memverifikasi nilai diterima. Kosong = default provider.
            </p>
          </div>

          <div className="col-span-2 space-y-2">
            <Label htmlFor="route_order">Routing pin (OpenRouter)</Label>
            <Input
              id="route_order"
              placeholder="z-ai"
              autoComplete="off"
              {...form.register("route_order")}
            />
            <p className="text-xs text-[var(--muted-foreground)]">
              Hard-pin upstream provider OpenRouter tanpa fallback (slug,
              dipisah koma untuk beberapa). Hanya isi untuk endpoint yang
              menerima field `provider` OpenRouter — verifikasi dengan Tes
              koneksi. Kosong = tidak di-pin.
            </p>
          </div>

          {testResult && (
            <div
              className={`col-span-2 max-h-40 overflow-y-auto whitespace-pre-wrap break-words rounded border p-2 text-xs ${
                testResult.ok
                  ? "border-green-600 text-green-700"
                  : "border-[var(--destructive)] text-[var(--destructive)]"
              }`}
            >
              {testResult.ok
                ? `OK${
                    testResult.latency_ms != null ? ` (${testResult.latency_ms} ms)` : ""
                  }: ${testResult.reply ?? ""}`
                : `Gagal: ${testResult.error ?? "error tidak diketahui"}`}
            </div>
          )}

          <DialogFooter className="col-span-2">
            <Button
              type="button"
              variant="outline"
              onClick={onTest}
              disabled={submitting || test.isPending}
            >
              {test.isPending ? "Menguji…" : "Tes koneksi"}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
            >
              Batal
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Menyimpan…" : isEdit ? "Simpan" : "Buat"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
