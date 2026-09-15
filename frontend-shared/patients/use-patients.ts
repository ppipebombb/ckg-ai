"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  asikPreview,
  decryptPatient,
  getPatient,
  listPatients,
  type PatientListQuery,
} from "./api";

export const patientsKeys = {
  all: ["patients"] as const,
  lists: () => [...patientsKeys.all, "list"] as const,
  list: (q: PatientListQuery) => [...patientsKeys.lists(), q] as const,
  detail: (id: string) => [...patientsKeys.all, "detail", id] as const,
  decrypted: (id: string) => [...patientsKeys.all, "decrypted", id] as const,
  asikPreview: (id: string) =>
    [...patientsKeys.all, "asik-preview", id] as const,
};

export function usePatientsList(q: PatientListQuery) {
  return useQuery({
    queryKey: patientsKeys.list(q),
    queryFn: () => listPatients(q),
    placeholderData: keepPreviousData,
  });
}

export function usePatient(id: string) {
  return useQuery({
    queryKey: patientsKeys.detail(id),
    queryFn: () => getPatient(id),
  });
}

export function useDecryptedPatient(id: string, enabled: boolean) {
  return useQuery({
    queryKey: patientsKeys.decrypted(id),
    queryFn: () => decryptPatient(id),
    enabled,
    staleTime: Infinity,
    gcTime: 5 * 60 * 1000,
  });
}

export function useAsikPreview(id: string, enabled: boolean) {
  // Deterministic on EPUS source. Re-scraping mutates the patient cache, not
  // this preview cache, so a fresh scrape only triggers a refetch via gcTime
  // expiry or an explicit invalidate from the scrape pipeline.
  return useQuery({
    queryKey: patientsKeys.asikPreview(id),
    queryFn: () => asikPreview(id),
    enabled,
    staleTime: Infinity,
    gcTime: Infinity,
  });
}
