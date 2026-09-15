import { asApiError } from "@/lib/api/client";

export function ErrorState({ error }: { error: unknown }) {
  const e = asApiError(error);
  return (
    <div className="rounded-md border border-[var(--destructive)]/40 bg-[var(--destructive)]/10 p-3 text-sm text-[var(--destructive)]">
      {e.messages.length > 1 ? (
        <ul className="list-disc pl-4 space-y-1">
          {e.messages.map((m, i) => <li key={i}>{m}</li>)}
        </ul>
      ) : (
        e.message
      )}
    </div>
  );
}
