"use client";

import { Timer } from "lucide-react";

import { useCountdown } from "@/hooks/use-countdown";
import { t } from "@/lib/strings";
import { cn } from "@/lib/utils";

export function Countdown({ expiresAt, className }: { expiresAt: string | null; className?: string }) {
  const countdown = useCountdown(expiresAt);
  if (!countdown) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium tabular-nums",
        countdown.urgent ? "bg-danger-soft text-danger" : "bg-muted text-muted-foreground",
        className,
      )}
    >
      <Timer className="size-3.5" />
      {countdown.expired ? t.orders.expired : `${countdown.label} ${t.orders.timeLeft}`}
    </span>
  );
}
