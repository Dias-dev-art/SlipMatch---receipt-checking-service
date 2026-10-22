import type { Metadata } from "next";

import { MenuView } from "@/components/menu/menu-view";
import { t } from "@/lib/strings";

export const metadata: Metadata = { title: t.menu.title };

export default function MenuPage() {
  return <MenuView />;
}
