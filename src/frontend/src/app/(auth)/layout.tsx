import { Brand } from "@/components/brand";
import { t } from "@/lib/strings";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <main className="flex min-h-svh flex-col items-center justify-center gap-6 bg-muted/40 px-4 py-10">
      <div className="flex flex-col items-center gap-2 text-center">
        <Brand className="text-xl" />
        <p className="max-w-xs text-sm text-muted-foreground">{t.tagline}</p>
      </div>
      <div className="w-full max-w-sm">{children}</div>
    </main>
  );
}
