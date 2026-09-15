"use client";

import { useRouter } from "next/navigation";
import { RefreshCw, Sparkles } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { asApiError } from "@/lib/api/client";
import { useStartPatientMerge } from "@/lib/hooks/use-merge";
import { useStartPatientScrape } from "@/lib/hooks/use-scrape";
import type { Patient } from "@shared/patients/types";

export function PatientActionBar({ patient }: { patient: Patient }) {
  const router = useRouter();
  const startScrape = useStartPatientScrape(patient.id);
  const startMerge = useStartPatientMerge(patient.id);

  const canMerge = patient.has_asik_data && patient.has_epus_data;

  const onMerge = async () => {
    try {
      const job = await startMerge.mutateAsync();
      toast.success("Merge dimulai");
      router.push(`/merge-with-ai/${job.id}`);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const onRescrapeAsik = async () => {
    try {
      const job = await startScrape.mutateAsync({ kind: "asik" });
      toast.success("Scrape ulang ASIK dimulai");
      router.push(`/scrape-jobs/${job.id}`);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  const onRescrapeEpus = async () => {
    try {
      const job = await startScrape.mutateAsync({ kind: "epus" });
      toast.success("Scrape ulang ePus dimulai");
      router.push(`/scrape-jobs/${job.id}`);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <Button
        size="sm"
        variant="outline"
        onClick={onRescrapeAsik}
        disabled={startScrape.isPending}
        title="Scrape ulang data ASIK pasien ini berdasarkan NIK"
      >
        <RefreshCw className="h-4 w-4" />
        Scrape ulang ASIK
      </Button>
      <Button
        size="sm"
        variant="outline"
        onClick={onRescrapeEpus}
        disabled={startScrape.isPending}
        title="Scrape ulang data ePus pasien ini memakai tanggal filter-nya"
      >
        <RefreshCw className="h-4 w-4" />
        Scrape ulang ePus
      </Button>
      <Button
        size="sm"
        variant="default"
        onClick={onMerge}
        disabled={!canMerge || startMerge.isPending}
        title={canMerge ? "Jalankan ulang merge LLM untuk pasien ini" : "Butuh data ASIK dan ePus hasil scrape sebelum merge"}
      >
        <Sparkles className="h-4 w-4" />
        Merge dengan AI
      </Button>
    </div>
  );
}
