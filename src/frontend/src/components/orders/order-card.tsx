"use client";

import { Countdown } from "@/components/orders/countdown";
import {
  OrderActions,
  CustomerContact,
  OrderAddress,
  OrderItems,
  OrderOutcome,
  OrderTotals,
  OrderTypeBadge,
  ProofThumbnail,
} from "@/components/orders/order-parts";
import { Card } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { customerHandle, customerName, formatMYR, formatRelative } from "@/lib/format";
import type { Order } from "@/lib/types";
import { cn } from "@/lib/utils";

/** Phone layout: one card per order. */
export function OrderCard({ order }: { order: Order }) {
  const hasDeliveryFee = Number(order.delivery_fee) > 0;

  return (
    <Card
      size="sm"
      className={cn(
        "gap-3",
        order.status === "payment_check" && "ring-2 ring-status-check/70",
        order.status === "cancelled" && "bg-muted/40",
      )}
    >
      <div className="flex items-start justify-between gap-3 px-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-lg leading-none font-semibold tracking-tight">{order.code}</span>
            <OrderTypeBadge type={order.order_type} />
          </div>
          <p className="mt-1.5 truncate text-xs text-muted-foreground">
            <span>{customerName(order.customer)}</span>
            {customerHandle(order.customer) && ` ${customerHandle(order.customer)}`}
            {" · "}
            {formatRelative(order.created_at)}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-lg leading-none font-semibold tabular-nums">{formatMYR(order.total)}</div>
          <Countdown expiresAt={order.expires_at} className="mt-1.5" />
        </div>
      </div>

      <div className="px-3">
        <OrderItems order={order} />
      </div>

      {hasDeliveryFee && (
        <div className="mx-3">
          <Separator className="mb-1.5" />
          <OrderTotals order={order} />
        </div>
      )}

      <OrderAddress order={order} className="px-3" />
      <CustomerContact customer={order.customer} className="px-3" />
      <ProofThumbnail order={order} className="mx-3" />
      <OrderOutcome order={order} className="px-3" />

      {(order.status === "payment_check" || order.status === "cancelled") && (
        <div className="px-3 pt-1">
          <OrderActions order={order} variant="card" />
        </div>
      )}
    </Card>
  );
}
