"use client";

import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  createUser,
  deleteUser,
  listUsers,
  updateUser,
  type UserListQuery,
} from "@/lib/api/users";
import type {
  Page,
  User,
  UserCreateInput,
  UserUpdateInput,
} from "@/lib/api/types";

export const userKeys = {
  all: ["users"] as const,
  list: (q: UserListQuery) => [...userKeys.all, "list", q] as const,
};

export function useUsersList(q: UserListQuery, enabled = true) {
  return useQuery({
    queryKey: userKeys.list(q),
    queryFn: () => listUsers(q),
    placeholderData: keepPreviousData,
    enabled,
  });
}

export function useCreateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (input: UserCreateInput) => createUser(input),
    onSuccess: (created) => {
      qc.setQueriesData<Page<User>>({ queryKey: userKeys.all }, (old) =>
        old
          ? { ...old, items: [created, ...old.items], total: old.total + 1 }
          : old,
      );
    },
  });
}

export function useUpdateUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: UserUpdateInput }) =>
      updateUser(id, input),
    onSuccess: (updated) => {
      qc.setQueriesData<Page<User>>({ queryKey: userKeys.all }, (old) =>
        old
          ? {
              ...old,
              items: old.items.map((u) => (u.id === updated.id ? updated : u)),
            }
          : old,
      );
    },
  });
}

export function useDeleteUser() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteUser(id),
    onSuccess: (_v, id) => {
      qc.setQueriesData<Page<User>>({ queryKey: userKeys.all }, (old) =>
        old
          ? {
              ...old,
              items: old.items.filter((u) => u.id !== id),
              total: Math.max(0, old.total - 1),
            }
          : old,
      );
    },
  });
}
