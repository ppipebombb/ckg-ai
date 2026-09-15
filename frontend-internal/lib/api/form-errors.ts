import type { FieldValues, Path, UseFormSetError } from "react-hook-form";
import { toast } from "sonner";
import { asApiError } from "./client";

const FIELD_PREFIX = /^([\w.]+):\s(.+)$/;

export function applyApiErrorToForm<T extends FieldValues>(
  err: unknown,
  setError: UseFormSetError<T>,
  knownFields: readonly Path<T>[],
): void {
  const e = asApiError(err);
  const leftovers: string[] = [];
  for (const m of e.messages) {
    const match = FIELD_PREFIX.exec(m);
    const field = match?.[1];
    const msg = match ? match[2] : m;
    if (field && (knownFields as readonly string[]).includes(field)) {
      setError(field as Path<T>, { message: msg });
    } else {
      leftovers.push(m);
    }
  }
  if (leftovers.length) {
    toast.error(leftovers.join("\n"));
  } else if (e.messages.length === 0) {
    toast.error(e.message);
  }
}
