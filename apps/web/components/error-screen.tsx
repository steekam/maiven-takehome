import { Button } from "@/components/ui/button";

type ErrorScreenProps = {
  title: string;
  description: string;
  reference?: string;
  reset: () => void;
};

export function ErrorScreen({ title, description, reference, reset }: ErrorScreenProps) {
  return (
    <main className="flex min-h-screen items-center justify-center bg-background px-6 py-12 text-foreground" role="alert">
      <section className="w-full max-w-lg rounded-lg border border-border bg-white p-8 shadow-sm">
        <a className="mb-8 inline-flex text-lg font-extrabold tracking-[-.06em] text-foreground no-underline" href="/" aria-label="Maiven home">maiven</a>
        <h1 className="m-0 text-2xl font-semibold tracking-[-.04em]">{title}</h1>
        <p className="mb-0 mt-3 text-sm leading-6 text-muted-foreground">{description}</p>
        {reference && <p className="mb-0 mt-3 font-mono text-xs text-muted-foreground">Reference: {reference}</p>}
        <div className="mt-6 flex flex-wrap items-center gap-3">
          <Button type="button" onClick={reset}>Try again</Button>
          <a className="text-sm font-medium text-foreground underline-offset-4 hover:underline" href="/">Back to EPA rules</a>
        </div>
      </section>
    </main>
  );
}
