import { http } from "./client";
import {
  MappingFormDetail,
  MappingFormSummary,
  MappingOverview,
  MappingEpusPath,
  PageSchema,
} from "./types";
import { z } from "zod";

const PageOfFormSummary = PageSchema(MappingFormSummary);

export const mappingApi = {
  async overview() {
    const { data } = await http.get("/admin/mapping/overview");
    return MappingOverview.parse(data);
  },

  async listForms(params: {
    q?: string;
    coverage?: "covered" | "partial" | "none";
    has_audit?: boolean;
    page: number;
    size: number;
  }) {
    const { data } = await http.get("/admin/mapping/forms", { params });
    return PageOfFormSummary.parse(data);
  },

  async getForm(frm_code: string) {
    const { data } = await http.get(`/admin/mapping/forms/${encodeURIComponent(frm_code)}`);
    return MappingFormDetail.parse(data);
  },

  async listEpusPaths(q?: string) {
    const { data } = await http.get("/admin/mapping/epus-paths", { params: { q } });
    return z.object({
      items: z.array(MappingEpusPath),
      total: z.number(),
    }).parse(data);
  },
};
