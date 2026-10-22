"use client";

import { Pencil, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { MenuItemDialog } from "@/components/menu/menu-item-dialog";
import { PageHeader } from "@/components/page-header";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useMediaQuery } from "@/hooks/use-media-query";
import { useDeleteMenuItem, useMenu, useSetAvailability } from "@/hooks/use-menu";
import { formatMYR } from "@/lib/format";
import { t } from "@/lib/strings";
import type { MenuItem } from "@/lib/types";
import { cn } from "@/lib/utils";

export function MenuView() {
  const { data: items, isPending } = useMenu();
  const deleteItem = useDeleteMenuItem();
  const [editing, setEditing] = useState<MenuItem | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [deleting, setDeleting] = useState<MenuItem | null>(null);
  const isDesktop = useMediaQuery("(min-width: 768px)");

  const categories = [...new Set((items ?? []).map((i) => i.category).filter((c): c is string => Boolean(c)))];
  const openEditor = (item: MenuItem | null) => {
    setEditing(item);
    setDialogOpen(true);
  };

  return (
    <>
      <PageHeader title={t.menu.title} description={t.menu.description}>
        <Button onClick={() => openEditor(null)}>
          <Plus />
          {t.menu.add}
        </Button>
      </PageHeader>

      {isPending ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-16 w-full rounded-xl" />
          ))}
        </div>
      ) : items?.length === 0 ? (
        <p className="rounded-xl border border-dashed px-4 py-12 text-center text-sm text-muted-foreground">
          {t.menu.empty}
        </p>
      ) : isDesktop ? (
        <Card className="py-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="pl-4">{t.menu.item}</TableHead>
                <TableHead>{t.menu.category}</TableHead>
                <TableHead>{t.menu.tags}</TableHead>
                <TableHead className="text-right">{t.menu.price}</TableHead>
                <TableHead>{t.menu.availableLabel}</TableHead>
                <TableHead className="w-24 pr-4 text-right">
                  <span className="sr-only">{t.menu.actions}</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {items?.map((item) => (
                <TableRow key={item.id} className={cn(!item.is_available && "text-muted-foreground")}>
                  <TableCell className="max-w-xs pl-4 whitespace-normal">
                    <div className="font-medium text-foreground">{item.name}</div>
                    <div className="line-clamp-1 text-xs text-muted-foreground">{item.description}</div>
                  </TableCell>
                  <TableCell>{item.category ?? "—"}</TableCell>
                  <TableCell className="max-w-56 whitespace-normal">
                    <Tags tags={item.tags} />
                  </TableCell>
                  <TableCell className="text-right font-medium tabular-nums">{formatMYR(item.price)}</TableCell>
                  <TableCell>
                    <AvailabilitySwitch item={item} />
                  </TableCell>
                  <TableCell className="pr-4 text-right">
                    <Button variant="ghost" size="icon" aria-label={t.common.edit} onClick={() => openEditor(item)}>
                      <Pencil />
                    </Button>
                    <Button variant="ghost" size="icon" aria-label={t.common.delete} onClick={() => setDeleting(item)}>
                      <Trash2 />
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      ) : (
        <div className="flex flex-col gap-2">
          {items?.map((item) => (
            <Card key={item.id} size="sm" className={cn("gap-2", !item.is_available && "bg-muted/40")}>
              <div className="flex items-start gap-3 px-3">
                <button type="button" className="min-w-0 flex-1 text-left" onClick={() => openEditor(item)}>
                  <div className="flex items-baseline justify-between gap-2">
                    <span className={cn("font-medium", !item.is_available && "text-muted-foreground line-through")}>
                      {item.name}
                    </span>
                    <span className="font-medium tabular-nums">{formatMYR(item.price)}</span>
                  </div>
                  {item.category && <div className="text-xs text-muted-foreground">{item.category}</div>}
                </button>
              </div>
              <div className="flex items-center justify-between gap-3 px-3">
                <Tags tags={item.tags} />
                <AvailabilitySwitch item={item} />
              </div>
            </Card>
          ))}
        </div>
      )}

      <MenuItemDialog open={dialogOpen} onOpenChange={setDialogOpen} item={editing} categories={categories} />

      <AlertDialog open={deleting !== null} onOpenChange={(open) => !open && setDeleting(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t.menu.deleteConfirmTitle}</AlertDialogTitle>
            <AlertDialogDescription>
              {deleting?.name}. {t.menu.deleteConfirmBody}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t.common.cancel}</AlertDialogCancel>
            <AlertDialogAction variant="destructive" onClick={() => deleting && deleteItem.mutate(deleting.id)}>
              {t.common.delete}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}

function Tags({ tags }: { tags: string[] }) {
  return (
    <div className="flex flex-wrap gap-1">
      {tags.map((tag) => (
        <Badge key={tag} variant="secondary" className="font-normal">
          {tag}
        </Badge>
      ))}
    </div>
  );
}

function AvailabilitySwitch({ item }: { item: MenuItem }) {
  const setAvailability = useSetAvailability();
  const id = `available-${item.id}`;
  return (
    <label htmlFor={id} className="flex shrink-0 items-center gap-2 text-xs">
      <Switch
        id={id}
        checked={item.is_available}
        onCheckedChange={(is_available) => setAvailability.mutate({ id: item.id, is_available })}
      />
      <span className={cn("w-14", item.is_available ? "text-foreground" : "font-medium text-danger")}>
        {item.is_available ? t.menu.available : t.menu.soldOut}
      </span>
    </label>
  );
}
