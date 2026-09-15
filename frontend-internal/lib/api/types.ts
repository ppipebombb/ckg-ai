import { z } from "zod";

export type Page<T> = {
  items: T[];
  total: number;
  page: number;
  size: number;
  pages: number;
};

export const PageSchema = <T extends z.ZodTypeAny>(item: T) =>
  z.object({
    items: z.array(item),
    total: z.number(),
    page: z.number(),
    size: z.number(),
    pages: z.number(),
  });

// Auth
export const TokenResponse = z.object({
  access_token: z.string(),
  token_type: z.string(),
});

export const AdminOut = z.object({
  id: z.string().uuid(),
  email: z.string().email(),
  full_name: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Admin = z.infer<typeof AdminOut>;

// Puskesmas
// Default domicile for the ASIK "create new patient" flow — the 4 admin levels
// picked from ASIK's teritorial-service so they match the registration cascade.
export const AsikAlamatLevel = z.object({ name: z.string(), code: z.string() });
export type AsikAlamatLevel = z.infer<typeof AsikAlamatLevel>;

export const AsikDefaultAlamat = z.object({
  provinsi: AsikAlamatLevel,
  kota: AsikAlamatLevel,
  kecamatan: AsikAlamatLevel,
  kelurahan: AsikAlamatLevel,
});
export type AsikDefaultAlamat = z.infer<typeof AsikDefaultAlamat>;

export const PuskesmasOut = z.object({
  id: z.string().uuid(),
  name: z.string(),
  epus_url: z.string().nullable(),
  asik_url: z.string().nullable(),
  asik_default_alamat: AsikDefaultAlamat.nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Puskesmas = z.infer<typeof PuskesmasOut>;

export const PuskesmasDetailOut = PuskesmasOut.extend({
  is_epus_cred_set: z.boolean(),
  is_asik_cred_set: z.boolean(),
});
export type PuskesmasDetail = z.infer<typeof PuskesmasDetailOut>;

const _BASE_DOMAIN_RE =
  /^(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}$/;

const baseDomain = z
  .string()
  .min(1, "Required")
  .regex(
    _BASE_DOMAIN_RE,
    "Base domain only (e.g. 'domain.com'), no scheme/path",
  );

export const PuskesmasCreate = z.object({
  name: z.string().min(1, "Name is required"),
  epus_url: baseDomain,
  asik_url: baseDomain,
  asik_default_alamat: AsikDefaultAlamat.nullable().optional(),
});
export type PuskesmasCreateInput = z.infer<typeof PuskesmasCreate>;

export const PuskesmasUpdate = z.object({
  name: z.string().min(1, "Name is required").optional(),
  epus_url: baseDomain.optional(),
  asik_url: baseDomain.optional(),
  asik_default_alamat: AsikDefaultAlamat.nullable().optional(),
});
export type PuskesmasUpdateInput = z.infer<typeof PuskesmasUpdate>;

export const CredIn = z.object({
  email: z.string().min(1),
  password: z.string().min(1),
});
export type CredInput = z.infer<typeof CredIn>;
export const CredOut = CredIn;

// User
export const UserOut = z.object({
  id: z.string().uuid(),
  email: z.string().email(),
  full_name: z.string(),
  puskesmas_id: z.string().uuid(),
  puskesmas_name: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type User = z.infer<typeof UserOut>;

export const UserCreate = z.object({
  email: z.string().email(),
  password: z.string().min(8).max(72),
  full_name: z.string().min(1),
  puskesmas_id: z.string().uuid(),
});
export type UserCreateInput = z.infer<typeof UserCreate>;

export const UserUpdate = z.object({
  email: z.string().email().optional(),
  password: z.string().min(8).max(72).optional().or(z.literal("")),
  full_name: z.string().min(1).optional(),
  puskesmas_id: z.string().uuid().optional(),
});
export type UserUpdateInput = z.infer<typeof UserUpdate>;

// LlmConfig
// Free-form: any value the chosen provider accepts (low/medium/high/xhigh,
// none/minimal, max, …). "" = use provider default (omit). Capped to match the
// backend column; Test connection is how you verify a value actually works.
export const ReasoningEffort = z.string().max(16);
export type ReasoningEffortT = z.infer<typeof ReasoningEffort>;

export const LlmConfigOut = z.object({
  id: z.string().uuid(),
  provider: z.string(),
  model: z.string(),
  base_url: z.string(),
  is_active: z.boolean(),
  is_active_captcha: z.boolean(),
  is_active_chatbot: z.boolean(),
  is_active_loop_agent: z.boolean(),
  is_active_loop_reviewer: z.boolean(),
  label: z.string().nullable(),
  reasoning_effort: z.string().nullable(),
  route_order: z.string().nullable(),
  input_price_per_1m: z.union([z.string(), z.number()]).nullable(),
  output_price_per_1m: z.union([z.string(), z.number()]).nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type LlmConfig = z.infer<typeof LlmConfigOut>;

const usdPrice = z
  .union([z.string(), z.number()])
  .nullish()
  .refine(
    (v) => v == null || v === "" || /^\d+(\.\d{1,2})?$/.test(String(v)),
    { message: "max 2 decimal places" },
  );

export const LlmConfigCreate = z.object({
  provider: z.string().min(1),
  model: z.string().min(1),
  base_url: z.string().url(),
  api_key: z.string().min(1),
  is_active: z.boolean(),
  is_active_captcha: z.boolean(),
  label: z.string().nullish(),
  reasoning_effort: ReasoningEffort.nullish(),
  route_order: z.string().nullish(),
  input_price_per_1m: usdPrice,
  output_price_per_1m: usdPrice,
});
export type LlmConfigCreateInput = z.infer<typeof LlmConfigCreate>;

export const LlmConfigUpdate = z.object({
  provider: z.string().min(1).optional(),
  model: z.string().min(1).optional(),
  base_url: z.string().url().optional(),
  api_key: z.string().min(1).optional().or(z.literal("")),
  label: z.string().nullish(),
  reasoning_effort: ReasoningEffort.nullish(),
  route_order: z.string().nullish(),
  input_price_per_1m: usdPrice,
  output_price_per_1m: usdPrice,
});
export type LlmConfigUpdateInput = z.infer<typeof LlmConfigUpdate>;

export const LlmConfigTestIn = z.object({
  provider: z.string().min(1),
  model: z.string().min(1),
  base_url: z.string().url(),
  reasoning_effort: ReasoningEffort.nullish(),
  route_order: z.string().nullish(),
  api_key: z.string().optional(),
  config_id: z.string().uuid().optional(),
});
export type LlmConfigTestInInput = z.infer<typeof LlmConfigTestIn>;

export const LlmConfigTestOut = z.object({
  ok: z.boolean(),
  model: z.string(),
  latency_ms: z.number().nullable().optional(),
  reply: z.string().nullable().optional(),
  error: z.string().nullable().optional(),
});
export type LlmConfigTestResult = z.infer<typeof LlmConfigTestOut>;

// LlmLog
export const LlmLogOut = z.object({
  id: z.string().uuid(),
  llm_config_id: z.string().uuid(),
  scrape_job_id: z.string().uuid().nullable(),
  merge_job_id: z.string().uuid().nullable().optional(),
  patient_id: z.string().uuid().nullable().optional(),
  puskesmas_id: z.string().uuid().nullable().optional(),
  source: z.string(),
  model: z.string(),
  input_tokens: z.number().nullable(),
  output_tokens: z.number().nullable(),
  reasoning_tokens: z.number().nullable(),
  total_tokens: z.number().nullable(),
  prompt_cost: z.union([z.string(), z.number()]).nullable(),
  completion_cost: z.union([z.string(), z.number()]).nullable(),
  total_cost: z.union([z.string(), z.number()]).nullable(),
  latency_ms: z.number().nullable(),
  success: z.boolean(),
  error: z.string().nullable(),
  created_at: z.string(),
  superseded_by_success: z.boolean().optional().default(false),
});
export type LlmLog = z.infer<typeof LlmLogOut>;

export const LlmUsageBucket = z.object({
  bucket: z.string(),
  calls: z.number(),
  input_tokens: z.number(),
  output_tokens: z.number(),
  prompt_cost: z.union([z.string(), z.number()]).nullable(),
  completion_cost: z.union([z.string(), z.number()]).nullable(),
  total_cost: z.union([z.string(), z.number()]).nullable(),
});
export type LlmUsageBucketT = z.infer<typeof LlmUsageBucket>;

// Scrape
export type ScrapeKind = "asik" | "epus" | "asik_sekolah";
export type ScrapeStatus =
  | "pending"
  | "running"
  | "success"
  | "failed"
  | "cancelled";

export const ScrapeJobOut = z.object({
  id: z.string().uuid(),
  puskesmas_id: z.string().uuid(),
  puskesmas_name: z.string(),
  patient_id: z.string().uuid().nullable(),
  patient_nik: z.string().nullable(),
  patient_name: z.string().nullable(),
  kind: z.enum(["asik", "epus", "asik_sekolah"]),
  date_filter: z.string().nullable(),
  status: z.enum(["pending", "running", "success", "failed", "cancelled"]),
  triggered_by_id: z.string().uuid(),
  triggered_by_type: z.enum(["admin", "user", "cron"]),
  celery_task_id: z.string().nullable(),
  scraped_count: z.number().nullable(),
  inserted_count: z.number().nullable(),
  updated_count: z.number().nullable(),
  duration_seconds: z.number().nullable(),
  cpu_avg_pct: z.number().nullable(),
  cpu_peak_pct: z.number().nullable(),
  mem_avg_mb: z.number().nullable(),
  mem_peak_mb: z.number().nullable(),
  resource_samples: z.number().nullable(),
  notes: z.string().nullable(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  error_message: z.string().nullable(),
  cron_run_id: z.string().uuid().nullable(),
  parent_gdp_job_id: z.string().uuid().nullable(),
  target_nik: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type ScrapeJob = z.infer<typeof ScrapeJobOut>;

export const ScrapeStart = z.object({
  date: z.string().nullish(),
});
export type ScrapeStartInput = z.infer<typeof ScrapeStart>;

export const ScrapeJobLogOut = z.object({
  lines: z.array(z.string()),
});

// Patient types live in the shared feature module now: @shared/patients/types

// Merge
export type MergeStatus =
  | "pending"
  | "running"
  | "success"
  | "failed"
  | "cancelled";

export const MergeJobOut = z.object({
  id: z.string().uuid(),
  puskesmas_id: z.string().uuid(),
  puskesmas_name: z.string(),
  patient_id: z.string().uuid().nullable(),
  patient_nik: z.string().nullable(),
  patient_name: z.string().nullable(),
  date_filter: z.string().nullable(),
  status: z.enum(["pending", "running", "success", "failed", "cancelled"]),
  triggered_by_id: z.string().uuid(),
  triggered_by_type: z.enum(["admin", "user", "cron"]),
  celery_task_id: z.string().nullable(),
  force_remerge: z.boolean(),
  total_count: z.number().nullable(),
  processed_count: z.number().nullable(),
  succeeded_count: z.number().nullable(),
  failed_count: z.number().nullable(),
  skipped_count: z.number().nullable(),
  duration_seconds: z.number().nullable(),
  cpu_avg_pct: z.number().nullable(),
  cpu_peak_pct: z.number().nullable(),
  mem_avg_mb: z.number().nullable(),
  mem_peak_mb: z.number().nullable(),
  resource_samples: z.number().nullable(),
  notes: z.string().nullable(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  error_message: z.string().nullable(),
  cron_run_id: z.string().uuid().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type MergeJob = z.infer<typeof MergeJobOut>;

export const MergeStart = z.object({
  date: z.string().nullish(),
  date_from: z.string().nullish(),
  date_to: z.string().nullish(),
  force: z.boolean(),
});
export type MergeStartInput = z.infer<typeof MergeStart>;

export const MergePreviewOut = z.object({
  matched_count: z.number(),
  pending_count: z.number(),
  already_merged_count: z.number(),
});
export type MergePreview = z.infer<typeof MergePreviewOut>;

export const MergeJobLogOut = z.object({
  lines: z.array(z.string()),
});

// Sync (ASIK form-fill)
export type SyncStatus =
  | "pending"
  | "running"
  | "success"
  | "failed"
  | "cancelled";

export const SyncJobOut = z.object({
  id: z.string().uuid(),
  puskesmas_id: z.string().uuid(),
  puskesmas_name: z.string(),
  patient_id: z.string().uuid(),
  patient_name: z.string(),
  patient_nik: z.string(),
  status: z.enum(["pending", "running", "success", "failed", "cancelled"]),
  triggered_by_id: z.string().uuid(),
  triggered_by_type: z.enum(["admin", "user", "cron"]),
  celery_task_id: z.string().nullable(),
  forms_total: z.number().nullable(),
  forms_succeeded: z.number().nullable(),
  forms_failed: z.number().nullable(),
  forms_skipped: z.number().nullable(),
  duration_seconds: z.number().nullable(),
  cpu_avg_pct: z.number().nullable(),
  cpu_peak_pct: z.number().nullable(),
  mem_avg_mb: z.number().nullable(),
  mem_peak_mb: z.number().nullable(),
  resource_samples: z.number().nullable(),
  notes: z.string().nullable(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  error_message: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type SyncJob = z.infer<typeof SyncJobOut>;

export const SyncJobLogOut = z.object({
  lines: z.array(z.string()),
});

// Capacity stats
const JobCapacityStatsOut = z.object({
  sample_size: z.number(),
  total_patients: z.number(),
  total_duration_sec: z.number(),
  avg_duration_per_patient_sec: z.number().nullable(),
  cpu_avg_pct: z.number().nullable(),
  cpu_peak_pct: z.number().nullable(),
  mem_avg_mb: z.number().nullable(),
  mem_peak_mb: z.number().nullable(),
  total_llm_cost_usd: z.number().nullable(),
  avg_llm_cost_per_patient_usd: z.number().nullable(),
});

export const CapacityStatsOut = z.object({
  window_days: z.number(),
  scrape: JobCapacityStatsOut,
  merge: JobCapacityStatsOut,
});
export type CapacityStats = z.infer<typeof CapacityStatsOut>;
export type JobCapacityStats = z.infer<typeof JobCapacityStatsOut>;

// Cron
export type CronRunStatus =
  | "pending"
  | "running"
  | "success"
  | "failed"
  | "cancelled";
export type CronStep = "asik" | "epus" | "merge" | "sync" | "create";

export const CronMergeMode = z.enum(["normal", "force_remerge", "no_merge"]);
export type CronMergeModeT = z.infer<typeof CronMergeMode>;

// Optional ASIK sync step after merge: off (default) | normal (only-not-synced) |
// force_resync (re-sync all). Mirrors CronMergeMode.
export const CronSyncMode = z.enum(["off", "normal", "force_resync"]);
export type CronSyncModeT = z.infer<typeof CronSyncMode>;

// "none" = sync-only backfill: no rescrape, run merge (matched-but-unmerged)
// then the ASIK sync step over existing data. Requires sync on + not no_merge.
export const CronSourceScope = z.enum(["both", "epus_only", "asik_only", "none"]);
export type CronSourceScopeT = z.infer<typeof CronSourceScope>;

export const CronConfigOut = z.object({
  id: z.string().uuid(),
  puskesmas_id: z.string().uuid(),
  hour: z.number().int().min(0).max(23),
  minute: z.number().int().min(0).max(59),
  target_offset_days: z.number().int().min(-1).max(0),
  lookback_days: z.number().int().min(1).max(14),
  enabled: z.boolean(),
  merge_mode: CronMergeMode,
  sync_mode: CronSyncMode,
  create_new: z.boolean(),
  next_run_at: z.string(),
  last_fired_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type CronConfig = z.infer<typeof CronConfigOut>;

export const CronConfigCreate = z
  .object({
    hour: z.number().int().min(0).max(23),
    minute: z.number().int().min(0).max(59),
    target_offset_days: z.number().int().min(-1).max(0),
    lookback_days: z.number().int().min(1).max(14),
    enabled: z.boolean(),
    merge_mode: CronMergeMode,
    sync_mode: CronSyncMode,
    create_new: z.boolean(),
  })
  // create_new runs AFTER the sync step, so it requires sync on — mirror backend.
  .refine((v) => !v.create_new || v.sync_mode !== "off", {
    message: "Create-in-ASIK requires ASIK sync to be on",
    path: ["create_new"],
  });
export type CronConfigCreateInput = z.infer<typeof CronConfigCreate>;

export const CronConfigUpdate = z.object({
  hour: z.number().int().min(0).max(23).optional(),
  minute: z.number().int().min(0).max(59).optional(),
  target_offset_days: z.number().int().min(-1).max(0).optional(),
  lookback_days: z.number().int().min(1).max(14).optional(),
  enabled: z.boolean().optional(),
  merge_mode: CronMergeMode.optional(),
  sync_mode: CronSyncMode.optional(),
  create_new: z.boolean().optional(),
});
export type CronConfigUpdateInput = z.infer<typeof CronConfigUpdate>;

export const CronRunOut = z.object({
  id: z.string().uuid(),
  cron_config_id: z.string().uuid().nullable(),
  cron_backfill_id: z.string().uuid().nullable(),
  puskesmas_id: z.string().uuid(),
  puskesmas_name: z.string(),
  target_date: z.string(),
  source_scope: CronSourceScope,
  status: z.enum(["pending", "running", "success", "failed", "cancelled"]),
  current_step: z.enum(["asik", "epus", "merge", "sync", "create"]).nullable(),
  current_step_attempt: z.number(),
  failed_step: z.enum(["asik", "epus", "merge", "sync", "create"]).nullable(),
  asik_scrape_job_id: z.string().uuid().nullable(),
  epus_scrape_job_id: z.string().uuid().nullable(),
  merge_job_id: z.string().uuid().nullable(),
  triggered_by_id: z.string().uuid().nullable(),
  error_message: z.string().nullable(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type CronRun = z.infer<typeof CronRunOut>;

// Per-patient ASIK-sync progress for one cron run. `total` is the denominator
// stamped when the sync step started; null for runs that never reached SYNC.
export const CronRunSyncSummaryOut = z.object({
  total: z.number().nullable(),
  pending: z.number(),
  running: z.number(),
  success: z.number(),
  failed: z.number(),
  cancelled: z.number(),
});
export type CronRunSyncSummary = z.infer<typeof CronRunSyncSummaryOut>;

export type CronBackfillStatus =
  | "pending"
  | "running"
  | "success"
  | "failed"
  | "cancelled";

export const CronBackfillCreate = z
  .object({
    puskesmas_id: z.string().uuid(),
    date_from: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    date_to: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
    merge_mode: CronMergeMode,
    source_scope: CronSourceScope,
    mandiri_only: z.boolean().optional(),
    sync_mode: CronSyncMode.optional(),
    create_new: z.boolean().optional(),
  })
  .refine((v) => v.date_from <= v.date_to, {
    message: "date_from must be <= date_to",
    path: ["date_to"],
  })
  // create_new runs after sync, so it requires sync on — mirror backend.
  .refine((v) => !v.create_new || (v.sync_mode ?? "off") !== "off", {
    message: "Create-in-ASIK requires ASIK sync to be on",
    path: ["create_new"],
  })
  // Source "none" is sync-only over existing data: it can't scrape (mandiri),
  // can't skip merge, and needs sync on — mirror the backend validator.
  .refine((v) => v.source_scope !== "none" || !v.mandiri_only, {
    message: "Source “None” cannot be combined with Pemeriksaan Mandiri",
    path: ["source_scope"],
  })
  .refine((v) => v.source_scope !== "none" || (v.sync_mode ?? "off") !== "off", {
    message: "Source “None” requires ASIK sync to be on",
    path: ["sync_mode"],
  })
  .refine((v) => v.source_scope !== "none" || v.merge_mode !== "no_merge", {
    message: "Source “None” cannot use No merge",
    path: ["merge_mode"],
  });
export type CronBackfillCreateInput = z.infer<typeof CronBackfillCreate>;

export const CronBackfillOut = z.object({
  id: z.string().uuid(),
  puskesmas_id: z.string().uuid(),
  puskesmas_name: z.string(),
  date_from: z.string(),
  date_to: z.string(),
  cursor_date: z.string().nullable(),
  status: z.enum(["pending", "running", "success", "failed", "cancelled"]),
  merge_mode: CronMergeMode,
  source_scope: CronSourceScope,
  mandiri_only: z.boolean(),
  sync_mode: CronSyncMode,
  create_new: z.boolean(),
  triggered_by_id: z.string().uuid().nullable(),
  current_cron_run_id: z.string().uuid().nullable(),
  total_dates: z.number().int(),
  completed_dates: z.number().int(),
  failed_date: z.string().nullable(),
  error_message: z.string().nullable(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type CronBackfill = z.infer<typeof CronBackfillOut>;

// Mapping (EPUS↔ASIK form metadata)
export const MappingChoice = z.object({
  line: z.union([z.string(), z.number()]).nullable(),
  code: z.string().nullable(),
  nilai_poin: z.number().nullable().optional(),
});

export const MappingQuestion = z.object({
  label: z.string(),
  parameter_codes: z.array(z.string()),
  tipe: z.string().nullable(),
  status_2026: z.string().nullable(),
  rekomendasi: z.string().nullable(),
  demos: z.array(z.string()),
  choices: z.array(MappingChoice),
  live_kind: z.string().nullable(),
  live_options: z.array(z.string()),
  live_name: z.string().nullable(),
  epus_source: z.string().nullable(),
  covered_by_converter: z.boolean(),
});
export type MappingQuestion = z.infer<typeof MappingQuestion>;

export const MappingFormSummary = z.object({
  frm_code: z.string().nullable(),
  paket_name: z.string(),
  modul: z.string().nullable(),
  layanan_name: z.string().nullable(),
  layanan_code: z.string().nullable(),
  question_count: z.number(),
  covered_question_count: z.number(),
  in_converter_breadcrumbs: z.boolean(),
  in_audit: z.boolean(),
  demos_union: z.array(z.string()),
  matched_questions: z.array(z.string()).default([]),
});
export type MappingFormSummary = z.infer<typeof MappingFormSummary>;

export const MappingFormDetail = MappingFormSummary.extend({
  audit_form_title: z.string().nullable(),
  questions: z.array(MappingQuestion),
});
export type MappingFormDetail = z.infer<typeof MappingFormDetail>;

export const MappingOverview = z.object({
  form_count: z.number(),
  question_count: z.number(),
  covered_question_count: z.number(),
  converter_form_count: z.number(),
  audit_form_count: z.number(),
  epus_path_count: z.number(),
  source_xlsx: z.string().nullable(),
  audit_dir: z.string().nullable(),
});
export type MappingOverview = z.infer<typeof MappingOverview>;

export const MappingEpusPath = z.object({
  path: z.string(),
  destinations: z.array(
    z.object({
      form_name: z.string(),
      frm_code: z.string().nullable(),
      label: z.string(),
    }),
  ),
});
export type MappingEpusPath = z.infer<typeof MappingEpusPath>;

// GDP Report
export const GdpReportStatus = z.enum([
  "pending",
  "running",
  "success",
  "failed",
  "cancelled",
]);
export type GdpReportStatus = z.infer<typeof GdpReportStatus>;

export const GdpReportPhase = z.enum(["pending", "asik", "epus", "done"]);
export type GdpReportPhase = z.infer<typeof GdpReportPhase>;

export const GdpReportJobOut = z.object({
  id: z.string().uuid(),
  puskesmas_id: z.string().uuid(),
  puskesmas_name: z.string(),
  date_from: z.string(),
  date_to: z.string(),
  triggered_by_id: z.string().uuid(),
  triggered_by_type: z.enum(["admin", "user", "cron"]),
  status: GdpReportStatus,
  phase: GdpReportPhase,
  celery_task_id: z.string().nullable(),
  nik_total: z.number().nullable(),
  nik_done: z.number(),
  dates_total: z.number(),
  dates_done: z.number(),
  epus_jobs_total: z.number().nullable(),
  epus_jobs_done: z.number(),
  epus_jobs_failed: z.number(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  error_message: z.string().nullable(),
  notes: z.string().nullable(),
  skip_asik_detail: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type GdpReportJob = z.infer<typeof GdpReportJobOut>;

export const GdpReportCreate = z.object({
  puskesmas_id: z.string().uuid({ message: "Pilih Puskesmas" }),
  date_from: z.string().min(1, "Required"),
  date_to: z.string().min(1, "Required"),
  skip_asik_detail: z.boolean(),
});
export type GdpReportCreateInput = z.infer<typeof GdpReportCreate>;

export const GdpReportRow = z.object({
  puskesmas_name: z.string(),
  tahun_pelaporan: z.number(),
  nama: z.string(),
  nik: z.string(),
  tanggal_diagnosis: z.string().nullable(),
  tertatalaksana_obat: z.boolean(),
  tertatalaksana_edukasi: z.boolean(),
  // Map of month number 1..12 → max GDP (mg/dl) or null. JSON arrives with
  // string keys; coerce to number on read.
  gdp_by_month: z.record(z.string(), z.number().nullable()),
  // Raw per-day readings for the Full Review Diagnose tab. Keyed by ISO date →
  // { lab, ptm }, each value nullable. Default {} for pre-existing caches.
  gdp_by_day: z
    .record(
      z.string(),
      z.object({ lab: z.number().nullable(), ptm: z.number().nullable() }),
    )
    .default({}),
  terkendali_bulan_berjalan: z.string(),
  terkendali_tw1: z.string(),
  terkendali_tw2: z.string(),
  terkendali_tw3: z.string(),
  terkendali_tw4: z.string(),
});
export type GdpReportRow = z.infer<typeof GdpReportRow>;

// Hipertensi Report — same shape as GDP but with a Sistolik + Diastolik pair
// per month instead of a single glucose value.
export const HipertensiReportRow = z.object({
  puskesmas_name: z.string(),
  tahun_pelaporan: z.number(),
  nama: z.string(),
  nik: z.string(),
  tanggal_diagnosis: z.string().nullable(),
  tertatalaksana_obat: z.boolean(),
  tertatalaksana_edukasi: z.boolean(),
  // Month number 1..12 → latest Sistolik / Diastolik (mmHg) or null. JSON
  // arrives with string keys; coerce to number on read.
  sistolik_by_month: z.record(z.string(), z.number().nullable()),
  diastolik_by_month: z.record(z.string(), z.number().nullable()),
  // Raw per-day readings for the Full Review Diagnose tab. ISO date →
  // { sys, dia }, each nullable. Default {} for pre-existing caches.
  bp_by_day: z
    .record(
      z.string(),
      z.object({ sys: z.number().nullable(), dia: z.number().nullable() }),
    )
    .default({}),
  terkendali_bulan_berjalan: z.string(),
  terkendali_tw1: z.string(),
  terkendali_tw2: z.string(),
  terkendali_tw3: z.string(),
  terkendali_tw4: z.string(),
});
export type HipertensiReportRow = z.infer<typeof HipertensiReportRow>;

// ── CKG Sekolah (school health checkup) ──
// SchoolPatient list/detail types live in frontend-shared/school-patients
// (shared by both apps). Only the internal-only School cron config types stay here.
export const SchoolCronConfigOut = z.object({
  id: z.string().uuid(),
  puskesmas_id: z.string().uuid(),
  hour: z.number().int().min(0).max(23),
  minute: z.number().int().min(0).max(59),
  enabled: z.boolean(),
  next_run_at: z.string(),
  last_fired_at: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type SchoolCronConfig = z.infer<typeof SchoolCronConfigOut>;

export const SchoolCronConfigCreate = z.object({
  hour: z.number().int().min(0).max(23),
  minute: z.number().int().min(0).max(59),
  enabled: z.boolean(),
});
export type SchoolCronConfigCreateInput = z.infer<typeof SchoolCronConfigCreate>;

export const SchoolCronConfigUpdate = z.object({
  hour: z.number().int().min(0).max(23).optional(),
  minute: z.number().int().min(0).max(59).optional(),
  enabled: z.boolean().optional(),
});
export type SchoolCronConfigUpdateInput = z.infer<typeof SchoolCronConfigUpdate>;

// ---- Loop agent ----
export const LoopRunStatusEnum = z.enum([
  "pending",
  "running",
  "covered",
  "no_data",
  "needs_review",
  "merged",
  "pr_rejected",
  "changes_ready",
  "bad_creds",
  "failed",
  "cancelled",
]);
export type LoopRunStatus = z.infer<typeof LoopRunStatusEnum>;

export const LoopTriggerEnum = z.enum(["manual", "nightly"]);
export type LoopTrigger = z.infer<typeof LoopTriggerEnum>;

export const LoopCoverageFinding = z.object({
  form: z.string().nullable().optional(),
  frm_code: z.string().nullable().optional(),
  status: z.string().nullable().optional(),
  questions: z.array(z.string()).optional(),
  epus_source: z.string().nullable().optional(),
  evidence: z.string().nullable().optional(),
  tabs_checked: z.array(z.string()).optional(),
  off_list: z.boolean().optional(),
});
export type LoopCoverageFindingType = z.infer<typeof LoopCoverageFinding>;

export const LoopRunOut = z.object({
  id: z.string().uuid(),
  puskesmas_id: z.string().uuid(),
  puskesmas_name: z.string(),
  trigger: z.enum(["manual", "nightly"]),
  triggered_by_id: z.string().uuid().nullable(),
  status: LoopRunStatusEnum,
  pin_ref: z.string().nullable(),
  open_pr: z.boolean().nullable(),
  container_name: z.string().nullable(),
  celery_task_id: z.string().nullable(),
  test_date: z.string().nullable(),
  live_count: z.number().nullable(),
  scraped_count: z.number().nullable(),
  decision: z.string().nullable(),
  gap_summary: z.string().nullable(),
  coverage_findings: z.array(LoopCoverageFinding).nullable(),
  branch_name: z.string().nullable(),
  pr_url: z.string().nullable(),
  review_verdict: z.string().nullable(),
  review_comments: z.string().nullable(),
  duration_seconds: z.number().nullable(),
  heartbeat_at: z.string().nullable(),
  started_at: z.string().nullable(),
  finished_at: z.string().nullable(),
  error_message: z.string().nullable(),
  event_count: z.number(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type LoopRun = z.infer<typeof LoopRunOut>;

export const LoopRunLogOut = z.object({
  lines: z.array(z.string()),
});

export const LoopRunSummaryOut = z.object({
  needs_action: z.number(),
  running: z.number(),
});
export type LoopRunSummary = z.infer<typeof LoopRunSummaryOut>;

export const LoopCoverageSummaryOut = z.object({
  total_questions: z.number(),
  mapped: z.number(),
  open: z.number(),
  documented_sourceless: z.number(),
  not_live: z.number(),
  label_drift: z.number(),
  deleted: z.number(),
  runs_with_findings: z.number(),
  forms_reported_absent: z.number(),
  generated_at: z.string(),
  ledger_updated: z.string(),
});
export type LoopCoverageSummary = z.infer<typeof LoopCoverageSummaryOut>;

export const LoopReconcileOut = z.object({
  checked: z.number(),
  merged: z.number(),
  rejected: z.number(),
});
export type LoopReconcileResult = z.infer<typeof LoopReconcileOut>;

export const LoopRunStart = z.object({
  puskesmas_id: z.string().uuid(),
  pin_ref: z.string().max(64).optional(),
  open_pr: z.boolean().optional(),
});
export type LoopRunStartInput = z.infer<typeof LoopRunStart>;

export const LoopMergeMode = z.enum(["manual", "auto"]);
export type LoopMergeModeValue = z.infer<typeof LoopMergeMode>;

export const LoopConfigOut = z.object({
  id: z.string().uuid(),
  merge_mode: LoopMergeMode,
  // Stored-but-unused placeholder for the later auto-deploy discussion.
  auto_deploy: z.boolean(),
  auto_open_pr: z.boolean(),
  nightly_budget: z.number(),
  max_fix_iterations: z.number(),
  max_review_iterations: z.number(),
  nightly_enabled: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type LoopConfig = z.infer<typeof LoopConfigOut>;

export const LoopConfigUpdate = z.object({
  merge_mode: LoopMergeMode.optional(),
  auto_deploy: z.boolean().optional(),
  auto_open_pr: z.boolean().optional(),
  nightly_budget: z.number().int().min(1).max(1000).optional(),
  max_fix_iterations: z.number().int().min(1).max(50).optional(),
  max_review_iterations: z.number().int().min(1).max(50).optional(),
  nightly_enabled: z.boolean().optional(),
});
export type LoopConfigUpdateInput = z.infer<typeof LoopConfigUpdate>;
