"use client";

import { Bike, Check, ImageIcon, MapPin, RotateCcw, ShoppingBag, X } from "lucide-react";

import { statusStyle } from "@/components/orders/status";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useOrderAction } from "@/hooks/use-orders";
import { formatMYR, formatTime } from "@/lib/format";
import { t } from "@/lib/strings";
import type { Order, OrderStatus } from "@/lib/types";
import { cn } from "@/lib/utils";

export function StatusBadge({ status }: { status: OrderStatus }) {
  return (
    <Badge className={cn("gap-1.5 border-0 font-medium", statusStyle[status].badge)}>
      <span className={cn("size-1.5 rounded-full", statusStyle[status].dot)} />
      {t.status[status]}
    </Badge>
  );
}

export function OrderTypeBadge({ type }: { type: Order["order_type"] }) {
  if (!type) return null;
  const Icon = type === "delivery" ? Bike : ShoppingBag;
  return (
    <Badge variant="outline" className="gap-1">
      <Icon className="size-3" />
      {type === "delivery" ? t.common.delivery : t.common.pickup}
    </Badge>
  );
}

export function OrderItems({ order }: { order: Order }) {
  return (
    <ul className="flex flex-col gap-1">
      {order.items.map((item) => (
        <li key={item.id} className="flex items-baseline gap-2">
          <span className="w-6 shrink-0 font-medium tabular-nums">{item.qty}×</span>
          <span className="min-w-0 flex-1">
            {item.name}
            {item.note && <span className="block text-xs text-muted-foreground italic">“{item.note}”</span>}
          </span>
          <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
            {formatMYR(item.unit_price)} {t.orders.each}
          </span>
        </li>
      ))}
    </ul>
  );
}

/** Totals exactly as the API returns them. */
export function OrderTotals({ order, showTotal = false }: { order: Order; showTotal?: boolean }) {
  return (
    <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-0.5 text-xs tabular-nums">
      <dt className="text-muted-foreground">{t.common.subtotal}</dt>
      <dd className="text-right">{formatMYR(order.subtotal)}</dd>
      <dt className="text-muted-foreground">{t.common.deliveryFee}</dt>
      <dd className="text-right">{formatMYR(order.delivery_fee)}</dd>
      {showTotal && (
        <>
          <dt className="font-medium">{t.common.total}</dt>
          <dd className="text-right font-semibold">{formatMYR(order.total)}</dd>
        </>
      )}
    </dl>
  );
}

export function OrderAddress({ order, className }: { order: Order; className?: string }) {
  if (order.order_type !== "delivery") return null;
  const hasPin = order.location_lat !== null && order.location_lng !== null;
  if (!order.address_text && !hasPin) return null;
  return (
    <div className={cn("flex items-start gap-1.5 text-xs", className)}>
      <MapPin className="mt-px size-3.5 shrink-0 text-muted-foreground" />
      <div className="min-w-0">
        {order.address_text && <p>{order.address_text}</p>}
        {hasPin && (
          <a
            href={`https://www.google.com/maps?q=${order.location_lat},${order.location_lng}`}
            target="_blank"
            rel="noreferrer"
            className="font-medium underline underline-offset-2"
          >
            {t.orders.openMap}
          </a>
        )}
      </div>
    </div>
  );
}

/** Cancel reason or approval time, when there is one. */
export function OrderOutcome({ order, className }: { order: Order; className?: string }) {
  if (order.status === "cancelled" && order.cancelled_reason) {
    return (
      <p className={cn("text-xs text-muted-foreground", className)}>
        {t.orders.cancelledReasons[order.cancelled_reason]}
      </p>
    );
  }
  if (order.status === "approved" && order.approved_at) {
    return (
      <p className={cn("flex items-center gap-1 text-xs text-status-approved", className)}>
        <Check className="size-3.5" />
        {t.orders.approvedAt} {formatTime(order.approved_at)}
      </p>
    );
  }
  return null;
}

export function ProofThumbnail({ order, className }: { order: Order; className?: string }) {
  const src = order.payment_proof_media_url;
  if (!src) return null;
  return (
    <Dialog>
      <DialogTrigger asChild>
        <button
          type="button"
          className={cn(
            "flex items-center gap-3 rounded-lg border bg-muted/40 p-1.5 pr-3 text-left text-xs transition-colors hover:bg-muted",
            className,
          )}
        >
          {/* eslint-disable-next-line @next/next/no-img-element -- remote media URLs from the API */}
          <img src={src} alt="" className="h-12 w-9 rounded object-cover object-top" />
          <span className="flex-1">
            <span className="block font-medium">{t.orders.paymentProof}</span>
            <span className="text-muted-foreground">{t.orders.viewProof}</span>
          </span>
          <ImageIcon className="size-4 text-muted-foreground" />
        </button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {t.orders.paymentProof} · {order.code} · {formatMYR(order.total)}
          </DialogTitle>
          <DialogDescription>{t.orders.paymentProofHint}</DialogDescription>
        </DialogHeader>
        {/* eslint-disable-next-line @next/next/no-img-element -- remote media URLs from the API */}
        <img src={src} alt={t.orders.paymentProof} className="max-h-[65svh] w-full rounded-lg object-contain" />
      </DialogContent>
    </Dialog>
  );
}

/** Approve / Not received for payment_check, Restore for cancelled. Disabled while any is pending. */
export function OrderActions({ order, variant }: { order: Order; variant: "card" | "row" }) {
  const approve = useOrderAction("approve");
  const notReceived = useOrderAction("not_received");
  const restore = useOrderAction("restore");
  const busy = approve.isPending || notReceived.isPending || restore.isPending;
  const size = variant === "card" ? "lg" : "sm";

  if (order.status === "payment_check") {
    return (
      <div className={variant === "card" ? "grid grid-cols-2 gap-2" : "flex justify-end gap-1.5"}>
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button variant="outline" size={size} disabled={busy}>
              <X />
              {t.orders.notReceived}
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>{t.orders.notReceivedConfirmTitle}</AlertDialogTitle>
              <AlertDialogDescription>
                {order.code} · {formatMYR(order.total)}. {t.orders.notReceivedConfirmBody}
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>{t.common.cancel}</AlertDialogCancel>
              <AlertDialogAction variant="destructive" onClick={() => notReceived.mutate(order.id)}>
                {t.orders.notReceivedConfirm}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
        <Button
          size={size}
          className="bg-status-approved text-status-approved-foreground hover:bg-status-approved/90"
          disabled={busy}
          onClick={() => approve.mutate(order.id)}
        >
          <Check />
          {t.orders.approve}
        </Button>
      </div>
    );
  }

  if (order.status === "cancelled") {
    return (
      <div className={variant === "card" ? undefined : "flex justify-end"}>
        <Button
          variant="outline"
          size={size === "lg" ? "default" : "sm"}
          className={variant === "card" ? "w-full" : undefined}
          disabled={busy}
          onClick={() => restore.mutate(order.id)}
        >
          <RotateCcw />
          {t.orders.restore}
        </Button>
      </div>
    );
  }

  return null;
}
