"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { FormRow } from "@/components/form-row";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { FieldError, FieldGroup } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { useAuth } from "@/hooks/use-auth";
import { t } from "@/lib/strings";

const schema = z.object({
  full_name: z.string().trim().min(1, t.auth.required),
  business_name: z.string().trim().min(1, t.auth.required),
  email: z.email(t.auth.emailInvalid),
  password: z.string().min(8, t.auth.passwordShort),
});

export function RegisterForm() {
  const router = useRouter();
  const { isAuthenticated, register } = useAuth();
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { full_name: "", business_name: "", email: "", password: "" },
  });
  const { errors, isSubmitting } = form.formState;

  useEffect(() => {
    if (isAuthenticated) router.replace("/orders");
  }, [isAuthenticated, router]);

  const onSubmit = form.handleSubmit(async (values) => {
    try {
      await register(values);
    } catch {
      form.setError("root", { message: t.common.somethingWrong });
    }
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">{t.auth.registerTitle}</CardTitle>
        <CardDescription>{t.auth.registerDescription}</CardDescription>
      </CardHeader>
      <form onSubmit={onSubmit} noValidate>
        <CardContent>
          <FieldGroup>
            <FormRow label={t.auth.fullName} htmlFor="full_name" error={errors.full_name}>
              <Input
                id="full_name"
                autoComplete="name"
                aria-invalid={Boolean(errors.full_name)}
                {...form.register("full_name")}
              />
            </FormRow>
            <FormRow label={t.auth.businessName} htmlFor="business_name" error={errors.business_name}>
              <Input
                id="business_name"
                autoComplete="organization"
                placeholder={t.auth.businessNamePlaceholder}
                aria-invalid={Boolean(errors.business_name)}
                {...form.register("business_name")}
              />
            </FormRow>
            <FormRow label={t.auth.email} htmlFor="email" error={errors.email}>
              <Input
                id="email"
                type="email"
                autoComplete="email"
                inputMode="email"
                aria-invalid={Boolean(errors.email)}
                {...form.register("email")}
              />
            </FormRow>
            <FormRow
              label={t.auth.password}
              htmlFor="password"
              description={t.auth.passwordShort}
              error={errors.password}
            >
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                aria-invalid={Boolean(errors.password)}
                {...form.register("password")}
              />
            </FormRow>
            <FieldError errors={[errors.root]} />
            <Button type="submit" size="lg" className="w-full" disabled={isSubmitting}>
              {isSubmitting ? t.common.loading : t.auth.registerButton}
            </Button>
          </FieldGroup>
        </CardContent>
      </form>
      <CardFooter className="justify-center gap-1 text-sm text-muted-foreground">
        {t.auth.haveAccount}
        <Link href="/login" className="font-medium text-foreground underline-offset-4 hover:underline">
          {t.auth.toLogin}
        </Link>
      </CardFooter>
    </Card>
  );
}
