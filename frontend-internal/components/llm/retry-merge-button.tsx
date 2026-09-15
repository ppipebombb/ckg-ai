"use client";

import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useStartPatientMerge } from "@/lib/hooks/use-merge";
import { asApiError } from "@/lib/api/client";

export function RetryMergeButton({ patientId }: { patientId: string }) {
  const router = useRouter();
  const m = useStartPatientMerge(patientId);
  const handleClick = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const job = await m.mutateAsync();
      toast.success("Ulang merge dimulai");
      router.push(`/merge-with-ai/${job.id}`);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };
  return (
    <Button
      size="sm"
      variant="secondary"
      disabled={m.isPending}
      onClick={handleClick}
    >
      <RefreshCw className="h-3.5 w-3.5" />
      Ulang merge
    </Button>
  );
}
