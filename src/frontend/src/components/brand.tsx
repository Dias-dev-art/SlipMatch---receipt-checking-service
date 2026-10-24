import { t } from "@/lib/strings";
import { cn } from "@/lib/utils";

export function Brand({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 font-semibold tracking-tight", className)}>
      {/* the logo has a white background, so it sits on a white tile in every theme */}
      <span className="grid size-8 place-items-center overflow-hidden rounded-lg bg-white ring-1 ring-black/5">
        {/* eslint-disable-next-line @next/next/no-img-element -- static export, no image optimizer */}
        <img src="/Waitly_Logo.png" alt="" className="size-7 object-contain" />
      </span>
      {t.appName}
    </span>
  );
}
