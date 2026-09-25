import type { ReactNode } from "react";
import { ArrowUpRight } from "lucide-react";
import { useDocumentLibrary } from "./provider";
import { formatTimestamp } from "@/lib/utils";

export function PageFrame({ children }: { children: ReactNode }) {
  return <main className="min-h-screen bg-background text-foreground">{children}</main>;
}

export function Masthead() {
  return <header className="flex h-16 items-center justify-between border-b border-border px-6 lg:px-12">
    <a className="inline-flex items-center gap-2.5 text-lg font-extrabold tracking-[-.06em] text-foreground no-underline" href="/" aria-label="Maiven home">
      <span className="relative inline-block size-5" aria-hidden="true"><i className="absolute bottom-0 left-0 size-2 rotate-[-35deg] rounded-[3px] bg-primary" /><i className="absolute left-[7px] top-[6px] size-2 rotate-[-35deg] rounded-[3px] bg-[#8068d8]" /><i className="absolute right-0 top-0 size-2 rotate-[-35deg] rounded-[3px] bg-[#58bca9]" /></span>
      maiven
    </a>
  </header>;
}

export function Hero() {
  const { meta } = useDocumentLibrary();
  return <section className="border-b border-border bg-white px-6 py-10 lg:px-12 lg:py-12">
    <div className="mx-auto max-w-[1320px]">
      <h1 className="m-0 max-w-3xl text-3xl font-semibold leading-tight tracking-[-.045em] sm:text-4xl">EPA rules</h1>
      <p className="mb-0 mt-3 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base">Published in the Federal Register by the U.S. Environmental Protection Agency.</p>
      <p className="mb-0 mt-2 text-xs text-muted-foreground" aria-live="polite">
        Last synced: {formatTimestamp(meta.lastSuccessfulAt)}
        {meta.freshnessNote ? ` · ${meta.freshnessNote}` : ""}
      </p>
    </div>
  </section>;
}

export function Content({ children }: { children: ReactNode }) {
  return <section className="mx-auto max-w-[1320px] px-4 py-8 sm:px-6 lg:px-12 lg:py-10" aria-label="EPA rules search and results">{children}</section>;
}

export function SearchRow({ children }: { children: ReactNode }) {
  return <div className="flex flex-col gap-3 sm:flex-row sm:items-center">{children}</div>;
}

export function Footer() {
  return <footer className="mx-auto flex min-h-[72px] max-w-[1320px] items-center justify-between gap-4 border-t border-border px-6 text-xs text-muted-foreground max-sm:flex-wrap max-sm:py-5 lg:px-12">
    <span className="text-sm font-extrabold tracking-[-.05em] text-foreground">maiven<span className="text-primary">.</span></span>
    <span>We make policy simple, so you can act with confidence.</span>
    <a className="no-underline hover:text-foreground" href="https://www.federalregister.gov/" target="_blank" rel="noreferrer">Source: Federal Register <ArrowUpRight className="inline size-3.5" /></a>
  </footer>;
}
