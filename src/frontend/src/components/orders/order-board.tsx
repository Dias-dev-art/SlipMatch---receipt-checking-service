"use client";

import { useState } from "react";

import { OrderCard } from "@/components/orders/order-card";
import { OrderTable } from "@/components/orders/order-table";
import { BOARD_COLUMNS, statusStyle, type BoardStatus } from "@/components/orders/status";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useOrders } from "@/hooks/use-orders";
import { t } from "@/lib/strings";
import type { Order } from "@/lib/types";
import { cn } from "@/lib/utils";

// Phone cards: most urgent first while a timer runs; newest first once settled.
const byExpiry = (a: Order, b: Order) => (a.expires_at ?? "").localeCompare(b.expires_at ?? "");
const byUpdated = (a: Order, b: Order) => b.updated_at.localeCompare(a.updated_at);
const sorters: Record<BoardStatus, (a: Order, b: Order) => number> = {
  payment_check: byExpiry,
  awaiting_payment: byExpiry,
  approved: byUpdated,
  cancelled: byUpdated,
};

export function OrderBoard() {
  const { data: orders, isPending, isError, refetch } = useOrders();
  const [active, setActive] = useState<BoardStatus>("payment_check");
  const isDesktop = useMediaQuery("(min-width: 1024px)");

  const columns = Object.fromEntries(
    BOARD_COLUMNS.map((status) => [
      status,
      (orders ?? []).filter((o) => o.status === status).sort(sorters[status]),
    ]),
  ) as Record<BoardStatus, Order[]>;

  return (
    <>
      <PageHeader title={t.orders.title} description={t.orders.description} />

      {isError ? (
        <div className="rounded-xl border border-dashed p-8 text-center text-sm text-muted-foreground">
          {t.orders.loadError}{" "}
          <Button variant="link" className="px-1" onClick={() => refetch()}>
            {t.orders.retry}
          </Button>
        </div>
      ) : isPending ? (
        // Neutral skeleton for both layouts: the server can't know the screen size.
        <div className="flex flex-col gap-3">
          <Skeleton className="h-12 w-full rounded-xl" />
          <Skeleton className="h-40 w-full rounded-xl" />
          <Skeleton className="h-32 w-full rounded-xl" />
        </div>
      ) : isDesktop ? (
        <OrderTable orders={orders ?? []} />
      ) : (
        <>
          <div role="group" aria-label={t.orders.title} className="mb-3 grid grid-cols-4 rounded-lg bg-muted p-[3px]">
            {BOARD_COLUMNS.map((status) => (
              <button
                key={status}
                type="button"
                aria-pressed={active === status}
                onClick={() => setActive(status)}
                className={cn(
                  "flex flex-col items-center gap-0.5 rounded-md py-1.5 text-xs font-medium text-foreground/60 transition-all",
                  active === status && "bg-background text-foreground shadow-sm",
                )}
              >
                <span className="flex items-center gap-1">
                  <span className={cn("size-1.5 rounded-full", statusStyle[status].dot)} />
                  {t.orders.tabs[status]}
                </span>
                <span className="text-sm font-semibold tabular-nums">{columns[status].length}</span>
              </button>
            ))}
          </div>
          <section aria-label={t.orders.columns[active]} className="flex flex-col gap-3">
            <p className="text-xs text-muted-foreground">{t.orders.columnHints[active]}</p>
            <OrderList status={active} orders={columns[active]} />
          </section>
        </>
      )}
    </>
  );
}

function OrderList({ status, orders }: { status: BoardStatus; orders: Order[] }) {
  if (orders.length === 0) {
    return (
      <p className="rounded-xl border border-dashed bg-background/60 px-4 py-8 text-center text-sm text-muted-foreground">
        {t.orders.empty[status]}
      </p>
    );
  }
  return (
    <div className="flex flex-col gap-3">
      {orders.map((order) => (
        <OrderCard key={order.id} order={order} />
      ))}
    </div>
  );
}
