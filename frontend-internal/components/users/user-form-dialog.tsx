"use client";

import { useEffect } from "react";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { toast } from "sonner";
import { z } from "zod";
import { UserCreate, type User } from "@/lib/api/types";
import { useCreateUser, useUpdateUser } from "@/lib/hooks/use-users";
import { usePuskesmas, usePuskesmasOptions } from "@/lib/hooks/use-puskesmas";
import { applyApiErrorToForm } from "@/lib/api/form-errors";
import { AsyncCombobox } from "@/components/ui/async-combobox";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";

const FormSchema = UserCreate.extend({
  password: z.string().optional(),
});

type FormValues = z.infer<typeof FormSchema>;

export function UserFormDialog({
  open,
  onOpenChange,
  user,
}: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  user?: User;
}) {
  const isEdit = !!user;
  const create = useCreateUser();
  const update = useUpdateUser();

  const form = useForm<FormValues>({
    resolver: zodResolver(FormSchema),
    defaultValues: {
      email: "",
      password: "",
      full_name: "",
      puskesmas_id: "",
    },
  });

  const watchedPuskesmasId = form.watch("puskesmas_id");
  const pkDetail = usePuskesmas(watchedPuskesmasId || undefined);

  useEffect(() => {
    if (open) {
      form.reset({
        email: user?.email ?? "",
        password: "",
        full_name: user?.full_name ?? "",
        puskesmas_id: user?.puskesmas_id ?? "",
      });
    }
  }, [open, user, form]);

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      if (isEdit) {
        await update.mutateAsync({
          id: user!.id,
          input: {
            email: values.email,
            full_name: values.full_name,
            puskesmas_id: values.puskesmas_id,
            password: values.password || undefined,
          },
        });
        toast.success("User updated");
      } else {
        if (!values.password || values.password.length < 8) {
          form.setError("password", {
            message: "Password must be at least 8 characters",
          });
          return;
        }
        await create.mutateAsync({ ...values, password: values.password });
        toast.success("User created");
      }
      onOpenChange(false);
    } catch (err) {
      applyApiErrorToForm(err, form.setError, ["email", "full_name", "password", "puskesmas_id"] as const);
    }
  });

  const submitting = create.isPending || update.isPending;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit user" : "New user"}</DialogTitle>
          <DialogDescription>
            {isEdit ? "Update this user's profile and puskesmas assignment." : "Create a user account scoped to a puskesmas."}
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="user-name">Full name</Label>
            <Input id="user-name" {...form.register("full_name")} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="user-email">Email</Label>
            <Input id="user-email" type="email" {...form.register("email")} />
          </div>
          <div className="space-y-2">
            <Label htmlFor="user-pw">
              Password {isEdit && <span className="text-[var(--muted-foreground)]">(leave blank to keep)</span>}
            </Label>
            <Input
              id="user-pw"
              type="password"
              autoComplete="new-password"
              {...form.register("password")}
            />
            {form.formState.errors.password && (
              <p className="text-xs text-[var(--destructive)]">
                {form.formState.errors.password.message}
              </p>
            )}
          </div>
          <div className="space-y-2">
            <Label>Puskesmas</Label>
            <Controller
              control={form.control}
              name="puskesmas_id"
              render={({ field }) => (
                <AsyncCombobox
                  value={field.value || undefined}
                  onChange={(v) => field.onChange(v ?? "")}
                  useOptions={usePuskesmasOptions}
                  selectedLabel={pkDetail.data?.name}
                  placeholder="Select puskesmas…"
                />
              )}
            />
            {form.formState.errors.puskesmas_id && (
              <p className="text-xs text-[var(--destructive)]">
                {form.formState.errors.puskesmas_id.message}
              </p>
            )}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => onOpenChange(false)}
              disabled={submitting}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Saving…" : isEdit ? "Save" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
