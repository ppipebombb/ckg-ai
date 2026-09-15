import { useQuery } from "@tanstack/react-query";
import {
  listAsikLocations,
  type AsikLocationLevel,
} from "@/lib/api/asik-locations";

export const asikLocationKeys = {
  all: ["asik-locations"] as const,
  list: (level: AsikLocationLevel, parentCode: string | undefined, search: string) =>
    [...asikLocationKeys.all, level, parentCode ?? null, search] as const,
};

// The AsyncCombobox option `id` is a single string, but a location needs both
// its `code` (to fetch the child level) and `name` (to store). Pack both into
// the id and unpack on selection. Codes are numeric and names never contain
// "␟" (unit separator), so the split is unambiguous.
const SEP = "␟";
export function packLoc(code: string, name: string): string {
  return `${code}${SEP}${name}`;
}
export function unpackLoc(id: string): { code: string; name: string } {
  const i = id.indexOf(SEP);
  return i < 0 ? { code: id, name: id } : { code: id.slice(0, i), name: id.slice(i + SEP.length) };
}

/**
 * Factory → an AsyncCombobox `useOptions(search)` bound to one cascade level and
 * its parent code. `province` is always enabled; child levels stay disabled
 * (empty) until their parent is chosen. The proxy returns the full filtered
 * match set in one call, so this is single-page (no infinite scroll).
 */
export function useAsikLocationOptions(
  level: AsikLocationLevel,
  parentCode: string | undefined,
) {
  return function useOptions(search: string) {
    const enabled = level === "province" || !!parentCode;
    const q = useQuery({
      queryKey: asikLocationKeys.list(level, parentCode, search),
      queryFn: () => listAsikLocations(level, parentCode, search),
      enabled,
      staleTime: 5 * 60_000,
    });
    return {
      options: (q.data ?? []).map((l) => ({ id: packLoc(l.code, l.name), label: l.name })),
      isLoading: enabled && q.isLoading,
      isFetchingNextPage: false,
      hasNextPage: false,
      fetchNextPage: () => {},
      error: q.error,
    };
  };
}
