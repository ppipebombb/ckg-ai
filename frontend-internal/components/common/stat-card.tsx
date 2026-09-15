import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

interface StatCardProps {
  title: string;
  value: string | number | undefined;
  subtext?: string;
  loading?: boolean;
}

export function StatCard({ title, value, subtext, loading }: StatCardProps) {
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm font-medium text-[var(--muted-foreground)]">
          {title}
        </CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-3xl font-semibold tabular-nums">
          {loading ? "—" : (value ?? "—")}
        </p>
        {subtext && (
          <p className="mt-1 text-xs text-[var(--muted-foreground)]">{subtext}</p>
        )}
      </CardContent>
    </Card>
  );
}
