// REFERENCE PAGE: copy its patterns (useAction, Field, ErrorBanner, inline validation) for every form.
import { useState, type FormEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { api } from "@/api/client";
import { Button, ErrorBanner, Field, Input } from "@/components/ui";
import { useAction } from "@/hooks/useApi";
import { setSession } from "@/lib/auth";

export default function LoginPage() {
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/floor";
  const [email, setEmail] = useState("owner@everest.test");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<{ email?: string; password?: string }>({});
  const login = useAction(api.auth.login);

  async function submit(e: FormEvent) {
    e.preventDefault();
    const errs: typeof fieldErrors = {};
    if (!/^[^@\s]+@[^@\s]+.[^@\s]+$/.test(email.trim())) {
      errs.email = "Enter a valid email address.";
    }
    if (!password) errs.password = "Enter your password.";
    setFieldErrors(errs);
    if (Object.keys(errs).length) return;

    const res = await login.run(email.trim(), password);
    if (res) {
      setSession(res);
      navigate(from, { replace: true });
    }
  }

  return (
    <div className="flex min-h-full items-center justify-center p-4">
      <form onSubmit={submit} noValidate className="w-full max-w-sm rounded-xl border border-line bg-surface p-6 shadow-sm">
        <div className="mb-6 flex items-center gap-2">
          <div className="grid size-8 place-items-center rounded-md bg-brand text-sm font-bold text-white">L</div>
          <div>
            <h1 className="font-semibold">LoomLedger</h1>
            <p className="text-sm text-muted">Everest Textile Mills</p>
          </div>
        </div>
        <div className="flex flex-col gap-4">
          <ErrorBanner error={login.error} />
          <Field label="Email" error={fieldErrors.email}>
            <Input type="email" autoComplete="username" value={email} aria-invalid={!!fieldErrors.email}
              onChange={(e) => setEmail(e.target.value)} />
          </Field>
          <Field label="Password" error={fieldErrors.password} hint="Demo password: demo1234">
            <Input type="password" autoComplete="current-password" value={password} aria-invalid={!!fieldErrors.password}
              onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <Button type="submit" loading={login.running} className="w-full">
            Sign in
          </Button>
        </div>
      </form>
    </div>
  );
}
