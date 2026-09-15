"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { usePuskesmasListStore } from "@/lib/stores/puskesmas-list-store";
import { ExternalLink, Pencil, Plus, Search, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Pagination } from "@/components/common/pagination";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { PuskesmasFormDialog } from "@/components/puskesmas/puskesmas-form-dialog";
import { ConfirmDialog } from "@/components/common/confirm-dialog";
import {
  useDeletePuskesmas,
  usePuskesmasList,
} from "@/lib/hooks/use-puskesmas";
import { useDebouncedValue } from "@/lib/hooks/use-debounced-value";
import { asApiError } from "@/lib/api/client";
import type { Puskesmas } from "@/lib/api/types";

export default function PuskesmasPage() {
  const page = usePuskesmasListStore((s) => s.page);
  const name = usePuskesmasListStore((s) => s.name);
  const setPage = usePuskesmasListStore((s) => s.setPage);
  const setName = usePuskesmasListStore((s) => s.setName);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<Puskesmas | null>(null);
  const [deleting, setDeleting] = useState<Puskesmas | null>(null);

  const debouncedName = useDebouncedValue(name);
  const query = useMemo(
    () => ({ page, size: 20, name: debouncedName.trim() || undefined }),
    [page, debouncedName],
  );
  const list = usePuskesmasList(query);
  const del = useDeletePuskesmas();

  const handleDelete = async () => {
    if (!deleting) return;
    try {
      await del.mutateAsync(deleting.id);
      toast.success("Puskesmas dihapus");
      setDeleting(null);
    } catch (err) {
      toast.error(asApiError(err).message);
    }
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Puskesmas"
        description="Pusat kesehatan dan kredensial scraper-nya."
        actions={
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            Puskesmas Baru
          </Button>
        }
      />

      <div className="relative max-w-sm">
        <Search className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-[var(--muted-foreground)]" />
        <Input
          placeholder="Cari berdasarkan nama…"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className="pl-8"
        />
      </div>

      {list.error && <ErrorState error={list.error} />}

      <div className="rounded-lg border border-[var(--border)]">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Nama</TableHead>
              <TableHead>EPUS</TableHead>
              <TableHead>ASIK</TableHead>
              <TableHead className="w-[120px]">Aksi</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {list.data?.items.map((p) => (
              <TableRow key={p.id}>
                <TableCell className="font-medium">
                  <Link
                    href={`/puskesmas/${p.id}`}
                    prefetch={false}
                    className="hover:underline"
                  >
                    {p.name}
                  </Link>
                </TableCell>
                <TableCell className="text-[var(--muted-foreground)]">
                  {p.epus_url ?? "—"}
                </TableCell>
                <TableCell className="text-[var(--muted-foreground)]">
                  {p.asik_url ?? "—"}
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      asChild
                      className="h-8 w-8"
                    >
                      <Link href={`/puskesmas/${p.id}`} prefetch={false}>
                        <ExternalLink className="h-4 w-4" />
                      </Link>
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setEditing(p)}
                      className="h-8 w-8"
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setDeleting(p)}
                      className="h-8 w-8 text-[var(--destructive)]"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {list.data && list.data.items.length === 0 && (
          <div className="p-6">
            <EmptyState
              title="Belum ada puskesmas"
              description={
                name
                  ? "Tidak ada yang cocok. Coba kata kunci lain."
                  : "Buat puskesmas pertama untuk memulai."
              }
            />
          </div>
        )}
      </div>

      {list.data && (
        <Pagination
          page={list.data.page}
          pages={list.data.pages}
          total={list.data.total}
          onPageChange={setPage}
        />
      )}

      <PuskesmasFormDialog
        open={createOpen || !!editing}
        onOpenChange={(v) => {
          if (!v) {
            setCreateOpen(false);
            setEditing(null);
          }
        }}
        puskesmas={editing ?? undefined}
      />

      <ConfirmDialog
        open={!!deleting}
        onOpenChange={(v) => !v && setDeleting(null)}
        title="Hapus puskesmas?"
        description={
          deleting
            ? `"${deleting.name}" akan dihapus beserta seluruh data terkait.`
            : undefined
        }
        confirmLabel="Hapus"
        destructive
        loading={del.isPending}
        onConfirm={handleDelete}
      />
    </div>
  );
}
