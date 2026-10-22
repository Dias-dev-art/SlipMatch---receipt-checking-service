"use client";

import { useEffect, useState } from "react";

export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}

/** Countdown to the API's `expires_at`. `urgent` under 2 minutes. */
export function useCountdown(expiresAt: string | null) {
  const now = useNow();
  if (!expiresAt) return null;
  const ms = Math.max(0, Date.parse(expiresAt) - now);
  const totalSeconds = Math.ceil(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return { label: `${minutes}:${seconds}`, expired: ms === 0, urgent: ms < 120_000 };
}
