"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { toast } from "sonner";

import { useChatPanel } from "@/components/handoff/chat-panel";
import { conversationKeys } from "@/hooks/use-conversations";
import { orderKeys } from "@/hooks/use-orders";
import * as api from "@/lib/api";
import { playPaymentAlert } from "@/lib/sound";
import { t } from "@/lib/strings";

/** Reacts to realtime events from the backend's SSE stream (/api/v1/events). */
export function useServerEvents() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const { openChat } = useChatPanel();

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
            // The AI passed this chat to the owner: they answer it in the chat panel (sent
            // through the bot) or give it back to the AI (it also resumes by itself after 24h).
            queryClient.invalidateQueries({ queryKey: conversationKeys.all });
            toast.warning(t.handoff.title, {
              description: t.handoff.body,
              duration: 30_000,
              action: { label: t.handoff.open, onClick: () => openChat(event.conversation_id) },
            });
            break;
        }
      }),
    [queryClient, router, openChat],
  );
}
