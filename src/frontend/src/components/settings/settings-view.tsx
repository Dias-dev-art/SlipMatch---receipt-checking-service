"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Plus, Trash2, Upload } from "lucide-react";
import { useRef } from "react";
import { Controller, useForm, useWatch, type Control, type FieldPath, type FieldValues } from "react-hook-form";
import { z } from "zod";

import { FormRow } from "@/components/form-row";
import { PageHeader } from "@/components/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardAction,
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
import {
  useAddExclusion,
  useBusiness,
  useExclusions,
  usePatchBusiness,
  usePutWhatsApp,
  useRemoveExclusion,
  useUploadPaymentQr,
} from "@/hooks/use-business";
import { formatPhone } from "@/lib/format";
import { t } from "@/lib/strings";
import type { Business } from "@/lib/types";
import { cn } from "@/lib/utils";

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
          <PaymentCard business={business} />
          <WhatsAppCard business={business} />
          <ExclusionsCard />
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

// --- WhatsApp ------------------------------------------------------------------

const whatsappSchema = z.object({
  phone_number_id: z.string().trim().regex(/^\d{6,20}$/, t.auth.required),
  display_phone: z.string().trim().min(1, t.auth.required),
  access_token: z.string().trim().min(1, t.auth.required),
});

function WhatsAppCard({ business }: { business: Business }) {
  const put = usePutWhatsApp();
  const connected = business.whatsapp !== null;
  const form = useForm<z.infer<typeof whatsappSchema>>({
    resolver: zodResolver(whatsappSchema),
    defaultValues: {
      phone_number_id: business.whatsapp?.phone_number_id ?? "",
      display_phone: business.whatsapp?.display_phone ?? "",
      access_token: "",
    },
  });
  const { errors, isDirty } = form.formState;

  const onSubmit = form.handleSubmit(async (values) => {
    const saved = await put.mutateAsync(values).catch(() => null);
    if (saved) form.reset({ ...values, access_token: "" });
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{s.whatsapp.title}</CardTitle>
        <CardDescription>{s.whatsapp.description}</CardDescription>
        <CardAction>
          <Badge
            variant="outline"
            className={connected ? "border-transparent bg-status-approved-soft text-status-approved" : "text-muted-foreground"}
          >
            <span className={cn("size-1.5 rounded-full", connected ? "bg-status-approved" : "bg-status-cancelled")} />
            {connected ? s.whatsapp.connected : s.whatsapp.notConnected}
          </Badge>
        </CardAction>
      </CardHeader>
      <form onSubmit={onSubmit} noValidate className="contents">
        <CardContent>
          <FieldGroup>
            <div className="grid gap-4 sm:grid-cols-2">
              <FormRow
                label={s.whatsapp.phoneNumberId}
                htmlFor="phone_number_id"
                description={s.whatsapp.phoneNumberIdHint}
                error={errors.phone_number_id}
              >
                <Input
                  id="phone_number_id"
                  inputMode="numeric"
                  aria-invalid={Boolean(errors.phone_number_id)}
                  {...form.register("phone_number_id")}
                />
              </FormRow>
              <FormRow label={s.whatsapp.displayPhone} htmlFor="display_phone" error={errors.display_phone}>
                <Input
                  id="display_phone"
                  inputMode="tel"
                  placeholder="+60 12-555 0199"
                  aria-invalid={Boolean(errors.display_phone)}
                  {...form.register("display_phone")}
                />
              </FormRow>
            </div>
            <FormRow
              label={s.whatsapp.accessToken}
              htmlFor="access_token"
              description={connected ? s.whatsapp.accessTokenSaved : s.whatsapp.accessTokenHint}
              error={errors.access_token}
            >
              <Input
                id="access_token"
                type="password"
                autoComplete="off"
                placeholder={connected ? "••••••••••••" : ""}
                aria-invalid={Boolean(errors.access_token)}
                {...form.register("access_token")}
              />
            </FormRow>
          </FieldGroup>
        </CardContent>
        <CardFooter className="justify-end border-t bg-muted/30 py-3">
          <Button type="submit" disabled={!isDirty || put.isPending}>
            {put.isPending ? t.common.saving : connected ? s.whatsapp.update : s.whatsapp.connect}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}

// --- Exclusions ----------------------------------------------------------------

const exclusionSchema = z.object({
  label: z.string().trim().min(1, t.auth.required).max(40),
  wa_phone: z.string().trim().regex(/^\d{8,15}$/, s.exclusions.phoneInvalid),
});

function ExclusionsCard() {
  const { data: exclusions, isPending } = useExclusions();
  const add = useAddExclusion();
  const remove = useRemoveExclusion();
  const form = useForm<z.infer<typeof exclusionSchema>>({
    resolver: zodResolver(exclusionSchema),
    defaultValues: { label: "", wa_phone: "" },
  });
  const { errors } = form.formState;

  const onSubmit = form.handleSubmit(async (values) => {
    const added = await add.mutateAsync(values).catch(() => null);
    if (added) form.reset();
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{s.exclusions.title}</CardTitle>
        <CardDescription>{s.exclusions.description}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {isPending ? (
          <Skeleton className="h-16 w-full" />
        ) : exclusions?.length === 0 ? (
          <p className="text-sm text-muted-foreground">{s.exclusions.empty}</p>
        ) : (
          <ul className="divide-y rounded-lg border">
            {exclusions?.map((exclusion) => (
              <li key={exclusion.id} className="flex items-center gap-3 px-3 py-2">
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{exclusion.label}</span>
                  <span className="text-xs text-muted-foreground">{formatPhone(exclusion.wa_phone)}</span>
                </span>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`${t.common.remove} ${exclusion.label}`}
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(exclusion.id)}
                >
                  <Trash2 />
                </Button>
              </li>
            ))}
          </ul>
        )}

        <form onSubmit={onSubmit} noValidate className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-start">
          <FormRow label={s.exclusions.label} htmlFor="exc-label" error={errors.label}>
            <Input
              id="exc-label"
              placeholder={s.exclusions.labelPlaceholder}
              aria-invalid={Boolean(errors.label)}
              {...form.register("label")}
            />
          </FormRow>
          <FormRow label={s.exclusions.phone} htmlFor="exc-phone" error={errors.wa_phone}>
            <Input
              id="exc-phone"
              inputMode="tel"
              placeholder={s.exclusions.phonePlaceholder}
              aria-invalid={Boolean(errors.wa_phone)}
              {...form.register("wa_phone")}
            />
          </FormRow>
          <Button type="submit" variant="outline" className="sm:mt-6" disabled={add.isPending}>
            <Plus />
            {s.exclusions.add}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
