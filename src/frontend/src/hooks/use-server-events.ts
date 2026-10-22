"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { toast } from "sonner";

import { orderKeys } from "@/hooks/use-orders";
import * as api from "@/lib/api";
import { toastError } from "@/lib/errors";
import { playPaymentAlert } from "@/lib/sound";
import { t } from "@/lib/strings";

/** Reacts to realtime events from the backend's SSE stream (/api/v1/events). */
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
          case "conversation.needs_owner":
            // The AI stopped answering this chat. The owner replies from the WhatsApp Business
            // app, or gives the chat back to the AI here (it also resumes by itself after 24h).
            toast.warning(t.handoff.title, {
              description: t.handoff.body,
              duration: 30_000,
              action: {
                label: t.handoff.resume,
                onClick: () =>
                  api
                    .resumeAi(event.conversation_id)
                    .then(() => toast.success(t.handoff.resumed))
                    .catch((error) => toastError(error)),
              },
            });
            break;
        }
      }),
    [queryClient, router],
  );
}
