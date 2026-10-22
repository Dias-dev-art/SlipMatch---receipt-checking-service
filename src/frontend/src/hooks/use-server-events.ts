"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { toast } from "sonner";

import { orderKeys } from "@/hooks/use-orders";
import * as api from "@/lib/mock-api";
import { playPaymentAlert } from "@/lib/sound";
import { t } from "@/lib/strings";

/**
 * Reacts to realtime events. Today they come from the mock API; with the backend this
 * becomes an EventSource on /api/v1/events?token=… (reconnect on error), same handler.
 */
export function useServerEvents() {
  const queryClient = useQueryClient();
  const router = useRouter();

  useEffect(
    () =>
      api.subscribeEvents((event) => {
        switch (event.type) {
          case "order.created":
          case "order.updated":
            queryClient.invalidateQueries({ queryKey: orderKeys.all });
            break;
          case "payment.check_requested":
            queryClient.invalidateQueries({ queryKey: orderKeys.all });
            playPaymentAlert();
            toast.warning(t.orders.alertTitle, {
              description: t.orders.alertBody,
              action: { label: t.orders.alertView, onClick: () => router.push("/orders") },
            });
            break;
        }
      }),
    [queryClient, router],
  );
}
