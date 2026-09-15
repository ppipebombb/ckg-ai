"use client";

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  decryptSchoolPatient,
  getSchoolFacets,
  listSchoolPatients,
  type SchoolPatientListQuery,
} from "./api";

export const schoolPatientsKeys = {
  all: ["school-patients"] as const,
  lists: () => [...schoolPatientsKeys.all, "list"] as const,
  list: (q: SchoolPatientListQuery) =>
    [...schoolPatientsKeys.lists(), q] as const,
  decrypted: (id: string) =>
    [...schoolPatientsKeys.all, "decrypted", id] as const,
  facets: (puskesmasId: string) =>
    [...schoolPatientsKeys.all, "facets", puskesmasId] as const,
};

export function useSchoolPatientsList(q: SchoolPatientListQuery) {
  return useQuery({
    queryKey: schoolPatientsKeys.list(q),
    queryFn: () => listSchoolPatients(q),
    placeholderData: keepPreviousData,
  });
}

export function useDecryptedSchoolPatient(id: string, enabled: boolean) {
  return useQuery({
    queryKey: schoolPatientsKeys.decrypted(id),
    queryFn: () => decryptSchoolPatient(id),
    enabled,
    staleTime: Infinity,
    gcTime: 5 * 60 * 1000,
  });
}

export function useSchoolFacets(puskesmasId: string) {
  return useQuery({
    queryKey: schoolPatientsKeys.facets(puskesmasId),
    queryFn: () => getSchoolFacets(puskesmasId || undefined),
    staleTime: 5 * 60 * 1000,
  });
}
