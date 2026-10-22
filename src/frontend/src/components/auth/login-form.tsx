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
  email: z.email(t.auth.emailInvalid),
  password: z.string().min(1, t.auth.required),
});

export function LoginForm() {
  const router = useRouter();
  const { isAuthenticated, login } = useAuth();
  const form = useForm<z.infer<typeof schema>>({
    resolver: zodResolver(schema),
    defaultValues: { email: "", password: "" },
  });
  const { errors, isSubmitting } = form.formState;

  useEffect(() => {
    if (isAuthenticated) router.replace("/orders");
  }, [isAuthenticated, router]);

  const onSubmit = form.handleSubmit(async ({ email, password }) => {
    try {
      await login(email, password);
    } catch {
      form.setError("root", { message: t.auth.invalidCredentials });
    }
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">{t.auth.loginTitle}</CardTitle>
        <CardDescription>{t.auth.loginDescription}</CardDescription>
      </CardHeader>
      <form onSubmit={onSubmit} noValidate>
        <CardContent>
          <FieldGroup>
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
            <FormRow label={t.auth.password} htmlFor="password" error={errors.password}>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                aria-invalid={Boolean(errors.password)}
                {...form.register("password")}
              />
            </FormRow>
            <FieldError errors={[errors.root]} />
            <Button type="submit" size="lg" className="w-full" disabled={isSubmitting}>
              {isSubmitting ? t.common.loading : t.auth.loginButton}
            </Button>
            <p className="rounded-md bg-muted px-3 py-2 text-center text-xs text-muted-foreground">
              {t.auth.demoHint}
            </p>
          </FieldGroup>
        </CardContent>
      </form>
      <CardFooter className="justify-center gap-1 text-sm text-muted-foreground">
        {t.auth.noAccount}
        <Link href="/register" className="font-medium text-foreground underline-offset-4 hover:underline">
          {t.auth.toRegister}
        </Link>
      </CardFooter>
    </Card>
  );
}
