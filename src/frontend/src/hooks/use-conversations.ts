"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { toastError } from "@/lib/errors";
import * as api from "@/lib/api";
import { t } from "@/lib/strings";

export const conversationKeys = {
  all: ["conversations"] as const,
  needingOwner: ["conversations", "needs_owner"] as const,
  messages: (id: string) => ["conversations", id, "messages"] as const,
};

/** Chats the AI handed to the owner (complaints, refunds). */
export function useChatsNeedingOwner() {
  return useQuery({
    queryKey: conversationKeys.needingOwner,
    queryFn: () => api.getConversations(true),
    // the conversation.needs_owner event invalidates it; polling is a safety net
    refetchInterval: 60_000,
  });
}

/** Recent chats (the panel reads one by id, also after it stopped needing the owner). */
export function useAllConversations() {
  return useQuery({ queryKey: conversationKeys.all, queryFn: () => api.getConversations() });
}

export function useConversationMessages(id: string | null) {
  return useQuery({
    queryKey: conversationKeys.messages(id ?? "none"),
    queryFn: () => api.getConversationMessages(id as string),
    enabled: id !== null,
    refetchInterval: 15_000, // new customer messages while the panel is open
  });
}

export function useReplyToConversation(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (text: string) => api.replyToConversation(id, text),
    onSuccess: () => toast.success(t.chat.sent),
    onError: (error) => toastError(error),
    onSettled: () => queryClient.invalidateQueries({ queryKey: conversationKeys.all }),
  });
}

export function useResumeAi() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.resumeAi(id),
    onSuccess: () => toast.success(t.handoff.resumed),
    onError: (error) => toastError(error),
    onSettled: () => queryClient.invalidateQueries({ queryKey: conversationKeys.all }),
  });
}
