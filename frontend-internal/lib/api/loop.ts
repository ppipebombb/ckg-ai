import { http } from "./client";
import {
  PageSchema,
  LoopRunOut,
  LoopRunLogOut,
  LoopConfigOut,
  LoopRunSummaryOut,
  LoopCoverageSummaryOut,
  LoopReconcileOut,
  type LoopConfig,
  type LoopConfigUpdateInput,
  type LoopCoverageSummary,
  type LoopReconcileResult,
  type LoopRun,
  type LoopRunStartInput,
  type LoopRunStatus,
  type LoopRunSummary,
  type LoopTrigger,
  type Page,
} from "./types";

export async function startLoopRun(input: LoopRunStartInput): Promise<LoopRun> {
  const { data } = await http.post(`/loop/runs`, input);
  return LoopRunOut.parse(data);
}

export type LoopRunListQuery = {
  page: number;
  size: number;
  puskesmas_id?: string;
  status?: LoopRunStatus;
  trigger?: LoopTrigger;
  needs_action?: boolean;
};

export async function listLoopRuns(q: LoopRunListQuery): Promise<Page<LoopRun>> {
  const { data } = await http.get(`/loop/runs`, { params: q });
  return PageSchema(LoopRunOut).parse(data);
}

export async function getLoopSummary(): Promise<LoopRunSummary> {
  const { data } = await http.get(`/loop/runs/summary`);
  return LoopRunSummaryOut.parse(data);
}

export async function getLoopCoverageSummary(): Promise<LoopCoverageSummary> {
  const { data } = await http.get(`/loop/coverage/summary`);
  return LoopCoverageSummaryOut.parse(data);
}

export async function reconcileLoopPrs(): Promise<LoopReconcileResult> {
  const { data } = await http.post(`/loop/runs/reconcile`);
  return LoopReconcileOut.parse(data);
}

export async function getLoopRun(runId: string): Promise<LoopRun> {
  const { data } = await http.get(`/loop/runs/${runId}`);
  return LoopRunOut.parse(data);
}

export async function getLoopRunLog(runId: string, tail = 300) {
  const { data } = await http.get(`/loop/runs/${runId}/log`, {
    params: { tail },
  });
  return LoopRunLogOut.parse(data);
}

export async function cancelLoopRun(runId: string): Promise<LoopRun> {
  const { data } = await http.post(`/loop/runs/${runId}/cancel`);
  return LoopRunOut.parse(data);
}

export async function openLoopRunPr(runId: string): Promise<LoopRun> {
  const { data } = await http.post(`/loop/runs/${runId}/open-pr`);
  return LoopRunOut.parse(data);
}

export async function getLoopConfig(): Promise<LoopConfig> {
  const { data } = await http.get(`/loop/config`);
  return LoopConfigOut.parse(data);
}

export async function updateLoopConfig(
  input: LoopConfigUpdateInput,
): Promise<LoopConfig> {
  const { data } = await http.patch(`/loop/config`, input);
  return LoopConfigOut.parse(data);
}
