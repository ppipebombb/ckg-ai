"use client";

import { useEffect, useMemo } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
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
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import {
  CronBackfillCreate,
  type CronBackfillCreateInput,
  type CronMergeModeT,
  type CronSourceScopeT,
} from "@/lib/api/types";
import { useCreateCronBackfill } from "@/lib/hooks/use-cron-backfill";
import {
  usePuskesmas,
  usePuskesmasOptions,
} from "@/lib/hooks/use-puskesmas";
import { applyApiErrorToForm } from "@/lib/api/form-errors";

const KNOWN_FIELDS = [
  "puskesmas_id",
  "date_from",
  "date_to",
  "merge_mode",
  "source_scope",
  "mandiri_only",
  "sync_mode",
  "create_new",
] as const;

function yesterdayJakartaISO(): string {
  const todayJakarta = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Jakarta",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
  const d = new Date(`${todayJakarta}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() - 1);
  return d.toISOString().slice(0, 10);
}

export function CronBackfillFormDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
}) {
  const create = useCreateCronBackfill();
  const defaultDate = useMemo(() => yesterdayJakartaISO(), []);

  const form = useForm<CronBackfillCreateInput>({
    resolver: zodResolver(CronBackfillCreate),
    defaultValues: {
      puskesmas_id: "",
      date_from: defaultDate,
      date_to: defaultDate,
      merge_mode: "normal",
      source_scope: "both",
      mandiri_only: false,
      sync_mode: "off",
      create_new: false,
    },
  });

  const puskesmasId = form.watch("puskesmas_id");
  const pkDetail = usePuskesmas(puskesmasId || undefined);
  const mandiriOnly = form.watch("mandiri_only") ?? false;
  const isNone = form.watch("source_scope") === "none";
  const syncMode = form.watch("sync_mode") ?? "off";
  const createNew = form.watch("create_new") ?? false;

  useEffect(() => {
    if (open) {
      form.reset({
        puskesmas_id: "",
        date_from: defaultDate,
        date_to: defaultDate,
        merge_mode: "normal",
        source_scope: "both",
        mandiri_only: false,
        sync_mode: "off",
        create_new: false,
      });
    }
  }, [open, defaultDate, form]);

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      await create.mutateAsync(values);
      toast.success("Backfill started");
      onOpenChange(false);
    } catch (err) {
      applyApiErrorToForm(err, form.setError, KNOWN_FIELDS);
    }
  });

  const pending = create.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Run for date range</DialogTitle>
          <DialogDescription>
            Scrapes the selected source(s) and runs Merge for each date in the
            range, forward, one day at a time. Cancellation preserves data for
            already-completed dates.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label>Puskesmas</Label>
            <AsyncCombobox
              value={puskesmasId || undefined}
              onChange={(v) =>
                form.setValue("puskesmas_id", v ?? "", {
                  shouldDirty: true,
                  shouldValidate: true,
                })
              }
              useOptions={usePuskesmasOptions}
              selectedLabel={pkDetail.data?.name}
              placeholder="Select a puskesmas…"
            />
            {form.formState.errors.puskesmas_id && (
              <p className="text-xs text-[var(--destructive)]">
                {form.formState.errors.puskesmas_id.message}
              </p>
            )}
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="bf-from">Date from</Label>
              <Input
                id="bf-from"
                type="date"
                {...form.register("date_from")}
              />
              {form.formState.errors.date_from && (
                <p className="text-xs text-[var(--destructive)]">
                  {form.formState.errors.date_from.message}
                </p>
              )}
            </div>
            <div className="space-y-2">
              <Label htmlFor="bf-to">Date to</Label>
              <Input id="bf-to" type="date" {...form.register("date_to")} />
              {form.formState.errors.date_to && (
                <p className="text-xs text-[var(--destructive)]">
                  {form.formState.errors.date_to.message}
                </p>
              )}
            </div>
          </div>

          <div className="flex items-start justify-between gap-4 rounded-md border border-[var(--border)] p-3">
            <div className="space-y-1">
              <Label htmlFor="bf-mandiri">Pemeriksaan Mandiri saja</Label>
              <p className="text-xs text-[var(--muted-foreground)]">
                Only scrapes the Pemeriksaan Mandiri (self-exam) forms for
                patients already in our DB who still lack it — Nakes/Tatalaksana
                are left untouched. Forces source to ASIK.
              </p>
            </div>
            <Switch
              id="bf-mandiri"
              checked={mandiriOnly}
              disabled={isNone}
              onCheckedChange={(v) => {
                form.setValue("mandiri_only", v, { shouldDirty: true });
                if (v) {
                  form.setValue("source_scope", "asik_only", {
                    shouldDirty: true,
                  });
                  if (form.getValues("merge_mode") === "normal") {
                    form.setValue("merge_mode", "force_remerge", {
                      shouldDirty: true,
                    });
                  }
                }
              }}
            />
          </div>

          <div className="space-y-2">
            <Label>Source</Label>
            <Select
              value={form.watch("source_scope")}
              onValueChange={(v) => {
                const scope = v as CronSourceScopeT;
                form.setValue("source_scope", scope, { shouldDirty: true });
                if (scope === "none") {
                  // Sync-only: needs sync on, can't be no_merge, can't be mandiri.
                  if ((form.getValues("sync_mode") ?? "off") === "off") {
                    form.setValue("sync_mode", "normal", { shouldDirty: true });
                  }
                  if (form.getValues("merge_mode") === "no_merge") {
                    form.setValue("merge_mode", "normal", { shouldDirty: true });
                  }
                  if (form.getValues("mandiri_only")) {
                    form.setValue("mandiri_only", false, { shouldDirty: true });
                  }
                }
              }}
              disabled={mandiriOnly}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="both">Both (EPUS + ASIK)</SelectItem>
                <SelectItem value="epus_only">EPUS only</SelectItem>
                <SelectItem value="asik_only">ASIK only</SelectItem>
                <SelectItem value="none">None (no rescrape — sync only)</SelectItem>
              </SelectContent>
            </Select>
            <p className="text-xs text-[var(--muted-foreground)]">
              {mandiriOnly
                ? "Locked to ASIK for a Pemeriksaan Mandiri backfill."
                : isNone
                  ? "No rescrape: merges any matched-but-unmerged patients from existing data, then pushes to ASIK. Requires ASIK sync on; runs alone (no other backfill for this puskesmas)."
                  : "Pick one source to scrape it alone (e.g. re-scrape EPUS, then merge). An EPUS-only and an ASIK-only run can run at the same time for one puskesmas. To run both single-source over the same dates, set one side to “No merge” (or use non-overlapping ranges) so the two merges don’t collide."}
            </p>
          </div>

          <div className="space-y-2">
            <Label>Merge mode</Label>
            <Select
              value={form.watch("merge_mode")}
              onValueChange={(v) =>
                form.setValue("merge_mode", v as CronMergeModeT, {
                  shouldDirty: true,
                })
              }
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="normal">Normal (merge new patients)</SelectItem>
                <SelectItem value="force_remerge">
                  Force re-merge (re-merge all)
                </SelectItem>
                {!isNone && (
                  <SelectItem value="no_merge">
                    No merge (scrape only — skip merge)
                  </SelectItem>
                )}
              </SelectContent>
            </Select>
            <p className="text-xs text-[var(--muted-foreground)]">
              Force re-merge re-runs the LLM on already-merged patients (extra
              cost). No merge scrapes only — use it while the LLM provider is
              down, then merge later.
              {isNone ? " No merge is unavailable for a sync-only (no-rescrape) run." : ""}
            </p>
          </div>

          {/* ASIK: fill toggle (sync_mode) + create toggle (create_new).
              Source = None (sync-only) makes sync mandatory, so "fill exam"
              is forced on there. Force sub-option maps
              normal↔force_resync. */}
          <div className="space-y-2 rounded-md border border-[var(--border)] p-3">
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-1">
                <Label htmlFor="bf-create-missing">
                  Also fill the ASIK exam for patients already in ASIK
                </Label>
                <p className="text-xs text-[var(--muted-foreground)]">
                  After each date&apos;s merge, fill the ASIK exam for patients
                  already in ASIK (NIK matched ePus + ASIK). Ignored when merge
                  mode is No merge.
                  {isNone ? " Required (and can’t be off) for a sync-only run." : ""}
                </p>
              </div>
              <Switch
                id="bf-create-missing"
                checked={syncMode !== "off"}
                disabled={isNone}
                onCheckedChange={(v) => {
                  if (v) {
                    form.setValue("sync_mode", "normal", { shouldDirty: true });
                  } else {
                    // Off clears the force sub-option and create-new — both
                    // require sync on (the backend rejects create_new + sync off).
                    form.setValue("sync_mode", "off", { shouldDirty: true });
                    form.setValue("create_new", false, { shouldDirty: true });
                  }
                }}
              />
            </div>
            {syncMode !== "off" && (
              <div className="ml-1 flex items-center gap-2">
                <input
                  id="bf-sync-force"
                  type="checkbox"
                  checked={syncMode === "force_resync"}
                  onChange={(e) =>
                    form.setValue(
                      "sync_mode",
                      e.target.checked ? "force_resync" : "normal",
                      { shouldDirty: true },
                    )
                  }
                />
                <Label
                  htmlFor="bf-sync-force"
                  className="cursor-pointer text-sm"
                >
                  Re-fill patients already synced (force re-sync)
                </Label>
              </div>
            )}
          </div>

          <div className="flex items-start justify-between gap-4 rounded-md border border-[var(--border)] p-3">
            <div className="space-y-1">
              <Label htmlFor="bf-create-new">
                Also create new patients in ASIK
              </Label>
              <p className="text-xs text-[var(--muted-foreground)]">
                After syncing each date, register ePus-only patients marked
                Tandai-CKG that are not yet in ASIK — creating them from scratch,
                then filling their exam. Requires &ldquo;fill exam&rdquo; on
                and a default alamat set on the puskesmas.
              </p>
              {form.formState.errors.create_new && (
                <p className="text-xs text-[var(--destructive)]">
                  {form.formState.errors.create_new.message}
                </p>
              )}
            </div>
            <Switch
              id="bf-create-new"
              checked={createNew}
              disabled={syncMode === "off"}
              onCheckedChange={(v) =>
                form.setValue("create_new", v, { shouldDirty: true })
              }
            />
          </div>

          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={pending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={pending}>
              {pending ? "Starting…" : "Start"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
