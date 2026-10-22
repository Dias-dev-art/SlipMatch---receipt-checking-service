"use client";

import { ArrowUpDown, ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";

import { Countdown } from "@/components/orders/countdown";
import {
  OrderActions,
  OrderAddress,
  OrderItems,
  OrderOutcome,
  OrderTotals,
  OrderTypeBadge,
  ProofThumbnail,
  StatusBadge,
} from "@/components/orders/order-parts";
import { BOARD_COLUMNS, STATUS_ORDER, statusStyle, type BoardStatus } from "@/components/orders/status";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { customerName, formatDateTime, formatMYR, formatPhone, formatRelative } from "@/lib/format";
import { t } from "@/lib/strings";
import type { Order } from "@/lib/types";
import { cn } from "@/lib/utils";

type Filter = "all" | BoardStatus;
type Sort = "status" | "newest" | "oldest";

const newest = (a: Order, b: Order) => b.created_at.localeCompare(a.created_at);
// Within a status: the timer that runs out first, then the newest.
const urgency = (a: Order, b: Order) =>
  a.expires_at && b.expires_at ? a.expires_at.localeCompare(b.expires_at) : newest(a, b);

const sorters: Record<Sort, (a: Order, b: Order) => number> = {
  status: (a, b) => STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) || urgency(a, b),
  newest,
  oldest: (a, b) => a.created_at.localeCompare(b.created_at),
};

const COLUMN_COUNT = 10;

/** Desktop layout: Shopify-style order list with status tabs, sorting and expandable rows. */
export function OrderTable({ orders }: { orders: Order[] }) {
  const [filter, setFilter] = useState<Filter>("all");
  const [sort, setSort] = useState<Sort>("status");
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());

  const count = (f: Filter) => (f === "all" ? orders.length : orders.filter((o) => o.status === f).length);
  const rows = orders.filter((o) => filter === "all" || o.status === filter).sort(sorters[sort]);

  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  return (
    <Card className="gap-0 py-0">
      <div className="flex items-end justify-between gap-4 border-b px-2">
        <div role="group" aria-label={t.orders.table.status} className="flex">
          {(["all", ...BOARD_COLUMNS] as const).map((f) => (
            <button
              key={f}
              type="button"
              aria-pressed={filter === f}
              onClick={() => setFilter(f)}
              className={cn(
                "-mb-px flex items-center gap-2 border-b-2 border-transparent px-3 py-3 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground",
                filter === f && "border-primary text-foreground",
              )}
            >
              {f !== "all" && <span className={cn("size-2 rounded-full", statusStyle[f].dot)} />}
              {f === "all" ? t.orders.table.all : t.orders.columns[f]}
              <span className="rounded-full bg-muted px-1.5 text-xs tabular-nums">{count(f)}</span>
            </button>
          ))}
        </div>
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="mb-2">
              <ArrowUpDown />
              {t.orders.sort.label}: {t.orders.sort[sort]}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-44">
            <DropdownMenuLabel>{t.orders.sort.label}</DropdownMenuLabel>
            <DropdownMenuRadioGroup value={sort} onValueChange={(value) => setSort(value as Sort)}>
              <DropdownMenuRadioItem value="status">{t.orders.sort.status}</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="newest">{t.orders.sort.newest}</DropdownMenuRadioItem>
              <DropdownMenuRadioItem value="oldest">{t.orders.sort.oldest}</DropdownMenuRadioItem>
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>

      {filter !== "all" && (
        <p className="border-b bg-muted/30 px-4 py-2 text-xs text-muted-foreground">{t.orders.columnHints[filter]}</p>
      )}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-10 pl-3">
              <span className="sr-only">{t.orders.table.expand}</span>
            </TableHead>
            <TableHead>{t.orders.table.order}</TableHead>
            <TableHead>{t.orders.table.date}</TableHead>
            <TableHead>{t.orders.table.customer}</TableHead>
            <TableHead>{t.orders.table.type}</TableHead>
            <TableHead>{t.orders.table.items}</TableHead>
            <TableHead className="text-right">{t.orders.table.total}</TableHead>
            <TableHead>{t.orders.table.status}</TableHead>
            <TableHead>{t.orders.table.timer}</TableHead>
            <TableHead className="pr-4 text-right">
              <span className="sr-only">{t.orders.table.actions}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.length === 0 ? (
            <TableRow className="hover:bg-transparent">
              <TableCell colSpan={COLUMN_COUNT} className="py-12 text-center text-muted-foreground">
                {filter === "all" ? t.orders.table.empty : t.orders.empty[filter]}
              </TableCell>
            </TableRow>
          ) : (
            rows.map((order) => (
              <OrderRow
                key={order.id}
                order={order}
                open={expanded.has(order.id)}
                onToggle={() => toggle(order.id)}
              />
            ))
          )}
        </TableBody>
      </Table>
    </Card>
  );
}

function OrderRow({ order, open, onToggle }: { order: Order; open: boolean; onToggle: () => void }) {
  const itemCount = order.items.reduce((n, item) => n + item.qty, 0);
  return (
    <Fragment>
      <TableRow
        onClick={onToggle}
        data-state={open ? "selected" : undefined}
        className={cn(
          "cursor-pointer",
          order.status === "payment_check" && "shadow-[inset_3px_0_0_var(--status-check)]",
          order.status === "cancelled" && "text-muted-foreground",
        )}
      >
        <TableCell className="pl-3">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-expanded={open}
            aria-label={`${t.orders.table.expand} ${order.code}`}
            onClick={(event) => {
              event.stopPropagation();
              onToggle();
            }}
          >
            <ChevronRight className={cn("transition-transform", open && "rotate-90")} />
          </Button>
        </TableCell>
        <TableCell className="font-mono font-semibold text-foreground">{order.code}</TableCell>
        <TableCell title={formatDateTime(order.created_at)}>{formatRelative(order.created_at)}</TableCell>
        <TableCell title={formatPhone(order.customer.wa_phone)} className="max-w-40 truncate">
          {customerName(order.customer)}
        </TableCell>
        <TableCell>
          <OrderTypeBadge type={order.order_type} />
        </TableCell>
        <TableCell className="text-muted-foreground">{t.orders.table.itemCount(itemCount)}</TableCell>
        <TableCell className="text-right font-medium text-foreground tabular-nums">
          {formatMYR(order.total)}
        </TableCell>
        <TableCell>
          <StatusBadge status={order.status} />
        </TableCell>
        <TableCell>
          <Countdown expiresAt={order.expires_at} />
        </TableCell>
        <TableCell className="pr-4">
          {/* Keep clicks (including ones inside the portalled confirm dialog) from toggling the row. */}
          <div onClick={(event) => event.stopPropagation()}>
            <OrderActions order={order} variant="row" />
          </div>
        </TableCell>
      </TableRow>
      {open && (
        <TableRow className="bg-muted/30 hover:bg-muted/30">
          <TableCell colSpan={COLUMN_COUNT} className="px-14 py-4 whitespace-normal">
            <div className="grid grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)_minmax(0,1fr)] gap-8">
              <OrderItems order={order} />
              <OrderTotals order={order} showTotal />
              <div className="flex flex-col gap-3">
                <OrderAddress order={order} />
                <ProofThumbnail order={order} className="w-fit" />
                <OrderOutcome order={order} />
              </div>
            </div>
          </TableCell>
        </TableRow>
      )}
    </Fragment>
  );
}
