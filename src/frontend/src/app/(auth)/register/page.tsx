import type { Metadata } from "next";

import { RegisterForm } from "@/components/auth/register-form";
import { t } from "@/lib/strings";

export const metadata: Metadata = { title: t.auth.registerTitle };

export default function RegisterPage() {
  return <RegisterForm />;
}
