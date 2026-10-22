import type { FieldError as RHFFieldError } from "react-hook-form";

import { Field, FieldDescription, FieldError, FieldLabel } from "@/components/ui/field";

/** Label + control + hint + error, wired for react-hook-form. */
export function FormRow({
  label,
  htmlFor,
  description,
  error,
  className,
  children,
}: {
  label: string;
  htmlFor: string;
  description?: string;
  error?: RHFFieldError;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Field data-invalid={Boolean(error)} className={className}>
      <FieldLabel htmlFor={htmlFor}>{label}</FieldLabel>
      {children}
      {description && !error && <FieldDescription>{description}</FieldDescription>}
      <FieldError errors={[error]} />
    </Field>
  );
}
