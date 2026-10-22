"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { toastError } from "@/lib/errors";
import * as api from "@/lib/mock-api";
import { t } from "@/lib/strings";

export const orderKeys = { all: ["orders"] as const };

export function useOrders() {
  return useQuery({
    queryKey: orderKeys.all,
    queryFn: api.getOrders,
    // Server events invalidate this too; polling is a safety net for missed events.
    refetchInterval: 30_000,
  });
}

export type OrderAction = "approve" | "not_received" | "restore";

const actions = {
  approve: { run: api.approveOrder, done: t.orders.approved },
  not_received: { run: api.markNotReceived, done: t.orders.notReceivedDone },
  restore: { run: api.restoreOrder, done: t.orders.restored },
} satisfies Record<OrderAction, { run: (id: string) => Promise<unknown>; done: string }>;

export function useOrderAction(action: OrderAction) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (orderId: string) => actions[action].run(orderId),
    onSuccess: () => toast.success(actions[action].done),
    // 409 means someone else or the timer already changed it: refetch either way.
    onError: (error) => toastError(error),
    onSettled: () => queryClient.invalidateQueries({ queryKey: orderKeys.all }),
  });
}

export function useSimulateCustomerPaid() {
  return useMutation({
    mutationFn: api.simulateCustomerPaid,
    onSuccess: (order) => {
      if (!order) toast.info(t.orders.simulateNone);
    },
    onError: (error) => toastError(error),
  });
}
