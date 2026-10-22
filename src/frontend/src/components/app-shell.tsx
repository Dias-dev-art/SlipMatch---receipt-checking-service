"use client";

import {
  ClipboardList,
  Laptop,
  LogOut,
  Moon,
  Settings,
  Sun,
  UtensilsCrossed,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect } from "react";

import { Brand } from "@/components/brand";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { useAuth, useMe } from "@/hooks/use-auth";
import { useOrders } from "@/hooks/use-orders";
import { useServerEvents } from "@/hooks/use-server-events";
import { initials } from "@/lib/format";
import { t } from "@/lib/strings";
import { cn } from "@/lib/utils";

interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  count?: number;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { token } = useAuth();
  const router = useRouter();
  const signedOut = token === null;

  useEffect(() => {
    if (signedOut) router.replace("/login");
  }, [signedOut, router]);

  // The server and first paint can't see the token (it lives in localStorage), so they render
  // the full shell with the page's loading state. Only a confirmed sign-out drops the page.
  if (signedOut) return <ShellSkeleton />;
  return <Shell>{children}</Shell>;
}

function Shell({ children }: { children: React.ReactNode }) {
  useServerEvents();
  const pathname = usePathname();
  const { data: me } = useMe();
  const { data: orders } = useOrders();

  const items: NavItem[] = [
    {
      href: "/orders",
      label: t.nav.orders,
      icon: ClipboardList,
      count: orders?.filter((o) => o.status === "payment_check").length,
    },
    { href: "/menu", label: t.nav.menu, icon: UtensilsCrossed },
    { href: "/settings", label: t.nav.settings, icon: Settings },
  ];
  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);

  return (
    <div className="min-h-svh md:grid md:grid-cols-[15rem_minmax(0,1fr)]">
      <aside className="sticky top-0 hidden h-svh flex-col gap-1 border-r bg-sidebar p-3 text-sidebar-foreground md:flex">
        <div className="px-2 pt-2 pb-1">
          <Brand />
        </div>
        <p className="truncate px-2 pb-4 text-xs text-sidebar-foreground/60">{me?.business.name ?? " "}</p>
        <nav className="flex flex-col gap-0.5">
          {items.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className={cn(
                "flex items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium text-sidebar-foreground/70 transition-colors hover:bg-sidebar-accent hover:text-sidebar-accent-foreground",
                isActive(item.href) && "bg-sidebar-accent text-sidebar-accent-foreground",
              )}
            >
              <item.icon className="size-4" />
              <span className="flex-1">{item.label}</span>
              <CountBadge count={item.count} />
            </Link>
          ))}
        </nav>
        <div className="mt-auto">
          <UserMenu name={me?.owner.full_name} email={me?.owner.email} />
        </div>
      </aside>

      <div className="flex min-w-0 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b bg-background/95 px-4 backdrop-blur md:hidden">
          <Brand />
          <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">{me?.business.name}</span>
          <UserMenu name={me?.owner.full_name} email={me?.owner.email} compact />
        </header>
        <main className="flex-1 px-4 pt-5 pb-28 md:px-8 md:py-8">{children}</main>
      </div>

      <nav className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-3 border-t bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
        {items.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={cn(
              "relative flex flex-col items-center gap-1 pt-2 pb-2.5 text-[0.7rem] font-medium text-muted-foreground",
              isActive(item.href) && "text-foreground",
            )}
          >
            <span className="relative">
              <item.icon className="size-5" />
              <CountBadge count={item.count} className="absolute -top-1.5 -right-3" />
            </span>
            {item.label}
          </Link>
        ))}
      </nav>
    </div>
  );
}

function CountBadge({ count, className }: { count?: number; className?: string }) {
  if (!count) return null;
  return (
    <span
      className={cn(
        "grid h-4.5 min-w-4.5 place-items-center rounded-full px-1 text-[0.65rem] leading-none font-semibold tabular-nums",
        "bg-status-check text-status-check-foreground",
        className,
      )}
    >
      {count}
    </span>
  );
}

const THEMES = [
  { value: "light", label: t.theme.light, icon: Sun },
  { value: "dark", label: t.theme.dark, icon: Moon },
  { value: "system", label: t.theme.system, icon: Laptop },
] as const;

function UserMenu({ name, email, compact }: { name?: string; email?: string; compact?: boolean }) {
  const { logout } = useAuth();
  const { theme, setTheme } = useTheme();
  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        className={cn(
          "flex items-center gap-2 rounded-lg text-left text-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50",
          !compact && "w-full p-2 hover:bg-sidebar-accent",
        )}
        aria-label={name}
      >
        <Avatar className="size-8">
          <AvatarFallback className="text-xs">{initials(name ?? "")}</AvatarFallback>
        </Avatar>
        {!compact && (
          <span className="min-w-0 flex-1">
            <span className="block truncate font-medium">{name}</span>
            <span className="block truncate text-xs text-sidebar-foreground/60">{email}</span>
          </span>
        )}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="font-normal">
          <span className="block truncate text-sm font-medium">{name}</span>
          <span className="block truncate text-xs text-muted-foreground">{email}</span>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuLabel className="text-xs font-normal text-muted-foreground">{t.theme.label}</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={theme} onValueChange={setTheme}>
          {THEMES.map(({ value, label, icon: Icon }) => (
            <DropdownMenuRadioItem key={value} value={value}>
              <Icon />
              {label}
            </DropdownMenuRadioItem>
          ))}
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem asChild>
          <Link href="/settings">
            <Settings />
            {t.nav.settings}
          </Link>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={logout}>
          <LogOut />
          {t.auth.logout}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

function ShellSkeleton() {
  return (
    <div className="min-h-svh md:grid md:grid-cols-[15rem_minmax(0,1fr)]">
      <aside className="hidden border-r bg-sidebar p-5 md:block">
        <Skeleton className="h-7 w-28" />
        <div className="mt-8 flex flex-col gap-3">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-6 w-full" />
          ))}
        </div>
      </aside>
      <div className="p-4 md:p-8">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="mt-6 h-48 w-full" />
      </div>
    </div>
  );
}
