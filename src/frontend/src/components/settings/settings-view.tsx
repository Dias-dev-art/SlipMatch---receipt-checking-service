"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy, Download, ExternalLink, Upload } from "lucide-react";
import { QRCodeCanvas } from "qrcode.react";
import { useRef } from "react";
import { Controller, useForm, useWatch, type Control, type FieldPath, type FieldValues } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";

import { FormRow } from "@/components/form-row";
import { PageHeader } from "@/components/page-header";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldContent, FieldDescription, FieldError, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { businessKeys, useBusiness, usePatchBusiness, useUploadPaymentQr } from "@/hooks/use-business";
import * as api from "@/lib/api";
import { isConflict, toastError } from "@/lib/errors";
import { t } from "@/lib/strings";
import type { Business } from "@/lib/types";

const s = t.settings;
const moneySchema = z.string().trim().regex(/^\d{1,4}(\.\d{1,2})?$/, t.menu.priceInvalid);

export function SettingsView() {
  const { data: business, isPending } = useBusiness();

  return (
    <div className="max-w-3xl">
      <PageHeader title={s.title} description={s.description} />
      {isPending || !business ? (
        <div className="flex flex-col gap-4">
          <Skeleton className="h-48 w-full rounded-xl" />
          <Skeleton className="h-48 w-full rounded-xl" />
        </div>
      ) : (
        <div className="flex flex-col gap-4">
          <BusinessCard business={business} />
          <OrderingCard business={business} />
          <TelegramCard business={business} />
          <PaymentCard business={business} />
        </div>
      )}
    </div>
  );
}

function SaveFooter({ disabled, pending }: { disabled: boolean; pending: boolean }) {
  return (
    <CardFooter className="justify-end border-t bg-muted/30 py-3">
      <Button type="submit" disabled={disabled || pending}>
        {pending ? t.common.saving : t.common.save}
      </Button>
    </CardFooter>
  );
}

function SwitchRow<T extends FieldValues>({
  control,
  name,
  label,
  description,
}: {
  control: Control<T>;
  name: FieldPath<T>;
  label: string;
  description: string;
}) {
  return (
    <Field orientation="horizontal">
      <FieldContent>
        <FieldLabel htmlFor={name}>{label}</FieldLabel>
        <FieldDescription>{description}</FieldDescription>
      </FieldContent>
      <Controller
        control={control}
        name={name}
        render={({ field }) => <Switch id={name} checked={field.value} onCheckedChange={field.onChange} />}
      />
    </Field>
  );
}

// --- Business ---------------------------------------------------------------

const businessSchema = z.object({
  name: z.string().trim().min(1, t.auth.required).max(80),
  greeting: z.string().trim().max(300),
});

function BusinessCard({ business }: { business: Business }) {
  const patch = usePatchBusiness();
  const form = useForm<z.infer<typeof businessSchema>>({
    resolver: zodResolver(businessSchema),
    defaultValues: { name: business.name, greeting: business.greeting ?? "" },
  });
  const { errors, isDirty } = form.formState;

  const onSubmit = form.handleSubmit(async (values) => {
    const saved = await patch.mutateAsync({ name: values.name, greeting: values.greeting || null }).catch(() => null);
    if (saved) form.reset(values);
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{s.business.title}</CardTitle>
        <CardDescription>{s.business.description}</CardDescription>
      </CardHeader>
      <form onSubmit={onSubmit} noValidate className="contents">
        <CardContent>
          <FieldGroup>
            <FormRow label={s.business.name} htmlFor="biz-name" error={errors.name}>
              <Input id="biz-name" aria-invalid={Boolean(errors.name)} {...form.register("name")} />
            </FormRow>
            <FormRow
              label={s.business.greeting}
              htmlFor="biz-greeting"
              description={s.business.greetingHint}
              error={errors.greeting}
            >
              <Textarea
                id="biz-greeting"
                rows={2}
                placeholder={s.business.greetingPlaceholder}
                {...form.register("greeting")}
              />
            </FormRow>
          </FieldGroup>
        </CardContent>
        <SaveFooter disabled={!isDirty} pending={patch.isPending} />
      </form>
    </Card>
  );
}

// --- Pickup and delivery ------------------------------------------------------

const orderingSchema = z
  .object({
    pickup_enabled: z.boolean(),
    delivery_enabled: z.boolean(),
    delivery_fee: moneySchema,
  })
  .refine((v) => v.pickup_enabled || v.delivery_enabled, {
    message: s.ordering.atLeastOne,
    path: ["pickup_enabled"],
  });

function OrderingCard({ business }: { business: Business }) {
  const patch = usePatchBusiness();
  const form = useForm<z.infer<typeof orderingSchema>>({
    resolver: zodResolver(orderingSchema),
    defaultValues: {
      pickup_enabled: business.pickup_enabled,
      delivery_enabled: business.delivery_enabled,
      delivery_fee: business.delivery_fee,
    },
  });
  const { errors, isDirty } = form.formState;
  const deliveryOn = useWatch({ control: form.control, name: "delivery_enabled" });

  const onSubmit = form.handleSubmit(async (values) => {
    const saved = await patch.mutateAsync(values).catch(() => null);
    if (saved) form.reset(values);
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{s.ordering.title}</CardTitle>
        <CardDescription>{s.ordering.description}</CardDescription>
      </CardHeader>
      <form onSubmit={onSubmit} noValidate className="contents">
        <CardContent>
          <FieldGroup>
            <SwitchRow
              control={form.control}
              name="pickup_enabled"
              label={s.ordering.pickup}
              description={s.ordering.pickupHint}
            />
            <SwitchRow
              control={form.control}
              name="delivery_enabled"
              label={s.ordering.delivery}
              description={s.ordering.deliveryHint}
            />
            {deliveryOn && (
              <FormRow
                label={s.ordering.deliveryFee}
                htmlFor="delivery_fee"
                error={errors.delivery_fee}
                className="max-w-40"
              >
                <Input
                  id="delivery_fee"
                  inputMode="decimal"
                  aria-invalid={Boolean(errors.delivery_fee)}
                  {...form.register("delivery_fee")}
                />
              </FormRow>
            )}
            <FieldError errors={[errors.pickup_enabled]} />
          </FieldGroup>
        </CardContent>
        <SaveFooter disabled={!isDirty} pending={patch.isPending} />
      </form>
    </Card>
  );
}

// --- Payment -------------------------------------------------------------------

const paymentSchema = z.object({
  payment_instructions: z.string().trim().min(1, t.auth.required).max(500),
  unique_amount_cents: z.boolean(),
  payment_timeout_minutes: z
    .number({ error: s.payment.timeoutInvalid })
    .int(s.payment.timeoutInvalid)
    .min(1, s.payment.timeoutInvalid)
    .max(60, s.payment.timeoutInvalid),
});

function PaymentCard({ business }: { business: Business }) {
  const patch = usePatchBusiness();
  const upload = useUploadPaymentQr();
  const fileRef = useRef<HTMLInputElement>(null);
  const form = useForm<z.infer<typeof paymentSchema>>({
    resolver: zodResolver(paymentSchema),
    defaultValues: {
      payment_instructions: business.payment_instructions,
      unique_amount_cents: business.unique_amount_cents,
      payment_timeout_minutes: business.payment_timeout_minutes,
    },
  });
  const { errors, isDirty } = form.formState;

  const onSubmit = form.handleSubmit(async (values) => {
    const saved = await patch.mutateAsync(values).catch(() => null);
    if (saved) form.reset(values);
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{s.payment.title}</CardTitle>
        <CardDescription>{s.payment.description}</CardDescription>
      </CardHeader>
      <form onSubmit={onSubmit} noValidate className="contents">
        <CardContent>
          <FieldGroup>
            <Field>
              <FieldLabel>{s.payment.qr}</FieldLabel>
              <div className="flex items-end gap-4">
                {business.payment_qr_url && (
                  // eslint-disable-next-line @next/next/no-img-element -- uploaded media URL from the API
                  <img
                    src={business.payment_qr_url}
                    alt={s.payment.qr}
                    className="size-32 rounded-lg border bg-white object-contain p-1" // QR codes need white to scan
                  />
                )}
                <div className="flex flex-col gap-2">
                  <input
                    ref={fileRef}
                    type="file"
                    accept="image/png,image/jpeg"
                    className="hidden"
                    onChange={(event) => {
                      const file = event.target.files?.[0];
                      if (file) upload.mutate(file);
                      event.target.value = "";
                    }}
                  />
                  <Button
                    type="button"
                    variant="outline"
                    disabled={upload.isPending}
                    onClick={() => fileRef.current?.click()}
                  >
                    <Upload />
                    {business.payment_qr_url ? s.payment.qrReplace : s.payment.qrUpload}
                  </Button>
                  <FieldDescription className="max-w-56">{s.payment.qrHint}</FieldDescription>
                </div>
              </div>
            </Field>
            <FormRow
              label={s.payment.instructions}
              htmlFor="payment_instructions"
              error={errors.payment_instructions}
            >
              <Textarea
                id="payment_instructions"
                rows={2}
                placeholder={s.payment.instructionsPlaceholder}
                aria-invalid={Boolean(errors.payment_instructions)}
                {...form.register("payment_instructions")}
              />
            </FormRow>
            <SwitchRow
              control={form.control}
              name="unique_amount_cents"
              label={s.payment.uniqueCents}
              description={s.payment.uniqueCentsHint}
            />
            <FormRow
              label={s.payment.timeout}
              htmlFor="payment_timeout_minutes"
              description={s.payment.timeoutHint}
              error={errors.payment_timeout_minutes}
            >
              <Input
                id="payment_timeout_minutes"
                type="number"
                inputMode="numeric"
                min={1}
                max={60}
                className="max-w-24"
                aria-invalid={Boolean(errors.payment_timeout_minutes)}
                {...form.register("payment_timeout_minutes", { valueAsNumber: true })}
              />
            </FormRow>
          </FieldGroup>
        </CardContent>
        <SaveFooter disabled={!isDirty} pending={patch.isPending} />
      </form>
    </Card>
  );
}

// --- Telegram ordering link ---------------------------------------------------

const shopCodeSchema = z.object({
  shop_code: z
    .string()
    .trim()
    .regex(/^[a-z0-9][a-z0-9-]{2,31}$/, s.telegram.shopCodeInvalid),
});

/** The shop's link to the shared Telegram bot, as text, buttons and a printable QR code. */
function TelegramCard({ business }: { business: Business }) {
  const queryClient = useQueryClient();
  const qrRef = useRef<HTMLCanvasElement>(null);
  const link = business.telegram_link;
  const form = useForm<z.infer<typeof shopCodeSchema>>({
    resolver: zodResolver(shopCodeSchema),
    defaultValues: { shop_code: business.shop_code },
  });
  const { errors, isDirty } = form.formState;
  const save = useMutation({
    mutationFn: (shop_code: string) => api.patchBusiness({ shop_code }),
    onSuccess: (saved) => {
      queryClient.setQueryData(businessKeys.all, saved);
      form.reset({ shop_code: saved.shop_code });
      toast.success(s.telegram.shopCodeSaved);
    },
    onError: (error) => {
      if (isConflict(error)) form.setError("shop_code", { message: s.telegram.shopCodeTaken });
      else toastError(error);
    },
  });

  const copy = () =>
    navigator.clipboard
      .writeText(link ?? "")
      .then(() => toast.success(s.telegram.copied))
      .catch((error) => toastError(error));

  const download = () => {
    const canvas = qrRef.current;
    if (!canvas) return;
    const a = document.createElement("a");
    a.href = canvas.toDataURL("image/png");
    a.download = `${business.shop_code}-telegram-qr.png`;
    a.click();
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{s.telegram.title}</CardTitle>
        <CardDescription>{s.telegram.description}</CardDescription>
      </CardHeader>
      <form onSubmit={form.handleSubmit((values) => save.mutate(values.shop_code))} noValidate className="contents">
        <CardContent>
          <FieldGroup>
            {link ? (
              <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
                <QRCodeCanvas
                  ref={qrRef}
                  value={link}
                  size={176}
                  marginSize={2}
                  // QR codes need dark on white to scan, whatever the theme
                  bgColor="#ffffff"
                  fgColor="#000000"
                  aria-label={s.telegram.qrAlt}
                  className="shrink-0 rounded-lg border"
                />
                <div className="flex min-w-0 flex-col gap-3">
                  <a
                    href={link}
                    target="_blank"
                    rel="noreferrer"
                    className="truncate rounded-md border bg-muted/40 px-3 py-2 font-mono text-sm underline-offset-2 hover:underline"
                  >
                    {link}
                  </a>
                  <div className="flex flex-wrap gap-2">
                    <Button type="button" variant="outline" onClick={copy}>
                      <Copy />
                      {s.telegram.copy}
                    </Button>
                    <Button type="button" variant="outline" asChild>
                      <a href={link} target="_blank" rel="noreferrer">
                        <ExternalLink />
                        {s.telegram.open}
                      </a>
                    </Button>
                    <Button type="button" variant="outline" onClick={download}>
                      <Download />
                      {s.telegram.download}
                    </Button>
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">{s.telegram.notReady}</p>
            )}
            <FormRow
              label={s.telegram.shopCode}
              htmlFor="shop-code"
              description={s.telegram.shopCodeHint}
              error={errors.shop_code}
            >
              <Input
                id="shop-code"
                autoComplete="off"
                spellCheck={false}
                className="font-mono"
                aria-invalid={Boolean(errors.shop_code)}
                {...form.register("shop_code")}
              />
            </FormRow>
          </FieldGroup>
        </CardContent>
        <SaveFooter disabled={!isDirty} pending={save.isPending} />
      </form>
    </Card>
  );
}
