import { Hourglass } from "lucide-react";

import { t } from "@/lib/strings";
import { cn } from "@/lib/utils";

export function Brand({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2 font-semibold tracking-tight", className)}>
      <span className="grid size-7 place-items-center rounded-lg bg-sidebar-primary text-sidebar-primary-foreground">
        <Hourglass className="size-4" />
      </span>
      {t.appName}
    </span>
  );
}
