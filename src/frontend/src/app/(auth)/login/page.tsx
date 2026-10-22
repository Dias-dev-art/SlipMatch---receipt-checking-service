import type { Metadata } from "next";

import { LoginForm } from "@/components/auth/login-form";
import { t } from "@/lib/strings";

export const metadata: Metadata = { title: t.auth.loginTitle };

export default function LoginPage() {
  return <LoginForm />;
}
