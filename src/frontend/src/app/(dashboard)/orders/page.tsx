import type { Metadata } from "next";

import { OrderBoard } from "@/components/orders/order-board";
import { t } from "@/lib/strings";

export const metadata: Metadata = { title: t.orders.title };

export default function OrdersPage() {
  return <OrderBoard />;
}
