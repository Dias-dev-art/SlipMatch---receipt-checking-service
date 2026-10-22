"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Plus } from "lucide-react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { z } from "zod";

import { FormRow } from "@/components/form-row";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { useSaveMenuItem } from "@/hooks/use-menu";
import { t } from "@/lib/strings";
import type { MenuItem } from "@/lib/types";

const SUGGESTED_TAGS = ["spicy", "halal", "vegetarian", "contains egg", "contains nuts", "contains seafood"];

const schema = z.object({
  name: z.string().trim().min(1, t.auth.required).max(80),
  price: z.string().trim().regex(/^\d{1,4}(\.\d{1,2})?$/, t.menu.priceInvalid),
  category: z.string().trim().max(40),
  description: z.string().trim().max(500),
  tags: z.string(),
  is_available: z.boolean(),
});
type FormValues = z.infer<typeof schema>;

const parseTags = (value: string) =>
  [...new Set(value.split(",").map((tag) => tag.trim().toLowerCase()).filter(Boolean))];

export function MenuItemDialog({
  open,
  onOpenChange,
  item,
  categories,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  item: MenuItem | null;
  categories: string[];
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90svh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{item ? t.menu.editTitle : t.menu.addTitle}</DialogTitle>
          <DialogDescription>{t.menu.dialogDescription}</DialogDescription>
        </DialogHeader>
        {/* Remounts per item so defaults always match what's being edited. */}
        <MenuItemForm key={item?.id ?? "new"} item={item} categories={categories} onDone={() => onOpenChange(false)} />
      </DialogContent>
    </Dialog>
  );
}

function MenuItemForm({
  item,
  categories,
  onDone,
}: {
  item: MenuItem | null;
  categories: string[];
  onDone: () => void;
}) {
  const save = useSaveMenuItem();
  const form = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      name: item?.name ?? "",
      price: item?.price ?? "",
      category: item?.category ?? "",
      description: item?.description ?? "",
      tags: item?.tags.join(", ") ?? "",
      is_available: item?.is_available ?? true,
    },
  });
  const { errors } = form.formState;
  const tags = parseTags(useWatch({ control: form.control, name: "tags" }));

  const addTag = (tag: string) => {
    form.setValue("tags", [...tags, tag].join(", "), { shouldDirty: true });
  };

  const onSubmit = form.handleSubmit(async (values) => {
    const saved = await save.mutateAsync({
      id: item?.id,
      input: {
        name: values.name,
        price: values.price,
        description: values.description,
        tags: parseTags(values.tags),
        category: values.category || null,
        is_available: values.is_available,
      },
    }).catch(() => null);
    if (saved) onDone();
  });

  return (
    <form onSubmit={onSubmit} noValidate>
      <FieldGroup className="gap-4">
        <div className="grid gap-4 sm:grid-cols-[1fr_8rem]">
          <FormRow label={t.menu.name} htmlFor="name" error={errors.name}>
            <Input id="name" aria-invalid={Boolean(errors.name)} {...form.register("name")} />
          </FormRow>
          <FormRow label={t.menu.price} htmlFor="price" error={errors.price}>
            <Input
              id="price"
              inputMode="decimal"
              placeholder="8.00"
              aria-invalid={Boolean(errors.price)}
              {...form.register("price")}
            />
          </FormRow>
        </div>
        <FormRow label={t.menu.category} htmlFor="category" error={errors.category}>
          <Input
            id="category"
            list="menu-categories"
            placeholder={t.menu.categoryPlaceholder}
            {...form.register("category")}
          />
          <datalist id="menu-categories">
            {categories.map((category) => (
              <option key={category} value={category} />
            ))}
          </datalist>
        </FormRow>
        <FormRow label={t.menu.descriptionLabel} htmlFor="description" error={errors.description}>
          <Textarea
            id="description"
            rows={3}
            placeholder={t.menu.descriptionPlaceholder}
            {...form.register("description")}
          />
        </FormRow>
        <FormRow label={t.menu.tags} htmlFor="tags" description={t.menu.tagsHint}>
          <Input id="tags" placeholder={t.menu.tagsPlaceholder} {...form.register("tags")} />
          <div className="flex flex-wrap gap-1.5">
            {tags.map((tag) => (
              <Badge key={tag} variant="secondary">
                {tag}
              </Badge>
            ))}
            {SUGGESTED_TAGS.filter((tag) => !tags.includes(tag)).map((tag) => (
              <button
                key={tag}
                type="button"
                onClick={() => addTag(tag)}
                className="inline-flex items-center gap-0.5 rounded-full border border-dashed px-2 py-0.5 text-xs text-muted-foreground hover:border-solid hover:text-foreground"
              >
                <Plus className="size-3" />
                {tag}
              </button>
            ))}
          </div>
        </FormRow>
        <Field orientation="horizontal">
          <Controller
            control={form.control}
            name="is_available"
            render={({ field }) => (
              <Switch id="is_available" checked={field.value} onCheckedChange={field.onChange} />
            )}
          />
          <FieldLabel htmlFor="is_available">{t.menu.availableLabel}</FieldLabel>
        </Field>
      </FieldGroup>
      <DialogFooter className="mt-6">
        <Button type="button" variant="outline" onClick={onDone}>
          {t.common.cancel}
        </Button>
        <Button type="submit" disabled={save.isPending}>
          {save.isPending ? t.common.saving : t.common.save}
        </Button>
      </DialogFooter>
    </form>
  );
}
