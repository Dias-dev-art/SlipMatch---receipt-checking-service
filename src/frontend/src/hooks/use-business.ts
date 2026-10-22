"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { toastError } from "@/lib/errors";
import * as api from "@/lib/mock-api";
import { t } from "@/lib/strings";
import type { Business } from "@/lib/types";

export const businessKeys = {
  all: ["business"] as const,
  exclusions: ["business", "exclusions"] as const,
};

export function useBusiness() {
  return useQuery({ queryKey: businessKeys.all, queryFn: api.getBusiness });
}

/** Wraps a settings call that returns the updated business. */
function useBusinessMutation<TInput>(fn: (input: TInput) => Promise<Business>, done: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: fn,
    onSuccess: (business) => {
      queryClient.setQueryData(businessKeys.all, business);
      queryClient.invalidateQueries({ queryKey: ["me"] });
      toast.success(done);
    },
    onError: (error) => toastError(error),
  });
}

export const usePatchBusiness = () => useBusinessMutation(api.patchBusiness, t.common.saved);
export const useUploadPaymentQr = () =>
  useBusinessMutation(api.uploadPaymentQr, t.settings.payment.qrUploaded);
export const usePutWhatsApp = () =>
  useBusinessMutation(api.putWhatsApp, t.settings.whatsapp.connectedToast);

export function useExclusions() {
  return useQuery({ queryKey: businessKeys.exclusions, queryFn: api.getExclusions });
}

export function useAddExclusion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.addExclusion,
    onSuccess: () => toast.success(t.settings.exclusions.added),
    onError: (error) => toastError(error),
    onSettled: () => queryClient.invalidateQueries({ queryKey: businessKeys.exclusions }),
  });
}

export function useRemoveExclusion() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: api.removeExclusion,
    onSuccess: () => toast.success(t.settings.exclusions.removed),
    onError: (error) => toastError(error),
    onSettled: () => queryClient.invalidateQueries({ queryKey: businessKeys.exclusions }),
  });
}
