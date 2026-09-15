"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useStartScrape } from "@/lib/hooks/use-scrape";
import type { ScrapeKind } from "@/lib/api/types";
import { asApiError } from "@/lib/api/client";

const todayJakarta = () =>
  new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Jakarta" }).format(new Date());

export function StartScrapeDialog({
  open,
  onOpenChange,
  puskesmasId,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  puskesmasId: string;
}) {
  const router = useRouter();
  const [kind, setKind] = useState<ScrapeKind>("asik");
  const [date, setDate] = useState(todayJakarta);
  const start = useStartScrape(puskesmasId);

  useEffect(() => {
    if (open) {
      setKind("asik");
      setDate(todayJakarta());
    }
  }, [open]);

  const isSekolah = kind === "asik_sekolah";

  const onSubmit = async () => {
    try {
      const job = await start.mutateAsync({
        kind,
        // CKG Sekolah is date-less (filtered by school × class). The backend
        // ignores date for asik_sekolah; send null.
        input: { date: isSekolah ? null : date || null },
      });
      toast.success("Scrape started");
      onOpenChange(false);
      router.push(`/scrape-jobs/${job.id}`);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Start scrape</DialogTitle>
          <DialogDescription>
            Runs a scraper for the given date. Defaults to today (Jakarta time).
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-2">
            <Label>Source</Label>
            <Select value={kind} onValueChange={(v) => setKind(v as ScrapeKind)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="asik">ASIK</SelectItem>
                <SelectItem value="epus">EPUS</SelectItem>
                <SelectItem value="asik_sekolah">CKG Sekolah</SelectItem>
              </SelectContent>
            </Select>
          </div>
          {isSekolah ? (
            <p className="text-xs text-[var(--muted-foreground)]">
              CKG Sekolah has no date — it scrapes every school × class for this
              puskesmas. This can take a while.
            </p>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="scrape-date">Date</Label>
              <Input
                id="scrape-date"
                type="date"
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </div>
          )}
        </div>
        <DialogFooter>
          <Button
            variant="outline"
            onClick={() => onOpenChange(false)}
            disabled={start.isPending}
          >
            Cancel
          </Button>
          <Button onClick={onSubmit} disabled={start.isPending}>
            {start.isPending ? "Starting…" : "Start"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
