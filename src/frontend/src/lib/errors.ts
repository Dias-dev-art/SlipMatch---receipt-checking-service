import { toast } from "sonner";

import { ApiError } from "@/lib/api";
import { t } from "@/lib/strings";

export function isConflict(error: unknown): boolean {
  return error instanceof ApiError && error.status === 409;
}

export function toastError(error: unknown, fallback: string = t.common.somethingWrong) {
  toast.error(isConflict(error) ? t.common.alreadyChanged : fallback);
}
