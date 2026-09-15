export function EmptyState({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-md border border-dashed border-[var(--border)] py-12 text-center">
      <p className="text-sm font-medium">{title}</p>
      {description && (
        <p className="mt-1 max-w-sm text-xs text-[var(--muted-foreground)]">
          {description}
        </p>
      )}
    </div>
  );
}
