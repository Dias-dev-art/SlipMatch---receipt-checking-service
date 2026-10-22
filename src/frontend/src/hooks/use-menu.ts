"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { toastError } from "@/lib/errors";
import * as api from "@/lib/mock-api";
import { t } from "@/lib/strings";
import type { MenuItem, MenuItemInput } from "@/lib/types";

export const menuKeys = { all: ["menu"] as const };

export function useMenu() {
  return useQuery({ queryKey: menuKeys.all, queryFn: api.getMenu });
}

export function useSaveMenuItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, input }: { id?: string; input: MenuItemInput }) =>
      id ? api.updateMenuItem(id, input) : api.createMenuItem(input),
    onSuccess: (_, { id }) => toast.success(id ? t.menu.updated : t.menu.created),
    onError: (error) => toastError(error),
    onSettled: () => queryClient.invalidateQueries({ queryKey: menuKeys.all }),
  });
}

export function useSetAvailability() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, is_available }: { id: string; is_available: boolean }) =>
      api.setAvailability(id, is_available),
    // Optimistic: the switch flips instantly.
    onMutate: async ({ id, is_available }) => {
      await queryClient.cancelQueries({ queryKey: menuKeys.all });
      const previous = queryClient.getQueryData<MenuItem[]>(menuKeys.all);
      queryClient.setQueryData<MenuItem[]>(menuKeys.all, (items) =>
        items?.map((item) => (item.id === id ? { ...item, is_available } : item)),
      );
      return { previous };
    },
    onSuccess: (item) =>
      toast.success(`${item.name} ${item.is_available ? t.menu.nowAvailable : t.menu.nowSoldOut}`),
    onError: (error, _, context) => {
      queryClient.setQueryData(menuKeys.all, context?.previous);
      toastError(error);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: menuKeys.all }),
  });
}

export function useDeleteMenuItem() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.deleteMenuItem,
    onSuccess: () => toast.success(t.menu.deleted),
    onError: (error) => toastError(error),
    onSettled: () => queryClient.invalidateQueries({ queryKey: menuKeys.all }),
  });
}
