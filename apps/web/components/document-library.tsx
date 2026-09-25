"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowDownUp, ArrowUp, ArrowUpRight, ChevronRight, FileText, Search, X } from "lucide-react";
import { parseAsString, useQueryState } from "nuqs";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetDismiss, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { DocumentLoadError, documentErrorMessage, isDocumentApiErrorCode } from "@/lib/documents/errors";

type DocumentResource = {
  id: string;
  attributes: {
    document_number: string;
    title: string;
    type: string;
    publication_date: string;
    effective_on: string | null;
    signing_date: string | null;
    comments_close_on: string | null;
    abstract: string | null;
    action: string | null;
    agency_names: string[] | null;
    citation: string | null;
    docket_ids: string[] | null;
    cfr_references: unknown[] | null;
    html_url: string;
    pdf_url: string | null;
  };
};

type DocumentPage = {
  links: { next: string | null };
  data: DocumentResource[];
  meta: {
    request_id: string;
    page: { size: number; hasMore: boolean };
    ingest: {
      last_successful_at: string | null;
      latest_run: {
        status: string;
        completion_reason: string | null;
        started_at: string;
        finished_at: string | null;
      } | null;
    };
  };
};

const sortColumns = [
  { key: "publication_date", label: "Published" },
  { key: "document_number", label: "Document no." },
  { key: "title", label: "Title" },
  { key: "type", label: "Type" },
  { key: "agency", label: "Agency" },
] as const;

function makeApiUrl(q: string, dateFrom: string, dateTo: string, sort: string) {
  const params = new URLSearchParams();
  if (q) params.set("filter[q]", q);
  if (dateFrom) params.set("filter[publication_date][gte]", dateFrom);
  if (dateTo) params.set("filter[publication_date][lte]", dateTo);
  params.set("sort", sort);
  params.set("page[size]", "20");
  return `/api/documents?${params.toString()}`;
}

function localDate(daysAgo = 0) {
  const date = new Date();
  date.setDate(date.getDate() - daysAgo);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function formatDate(date: string | null) {
  if (!date) return "—";
  return new Intl.DateTimeFormat("en", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(`${date}T00:00:00Z`));
}

function formatTimestamp(timestamp: string | null) {
  if (!timestamp) return "Not synced yet";
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  }).format(new Date(timestamp));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isStringOrNull(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isStringArrayOrNull(value: unknown): value is string[] | null {
  return value === null || (Array.isArray(value) && value.every((item) => typeof item === "string"));
}

function isDocumentResource(value: unknown): value is DocumentResource {
  if (!isRecord(value) || typeof value.id !== "string" || !isRecord(value.attributes)) return false;
  const attributes = value.attributes;
  return typeof attributes.document_number === "string"
    && typeof attributes.title === "string"
    && typeof attributes.type === "string"
    && typeof attributes.publication_date === "string"
    && isStringOrNull(attributes.effective_on)
    && isStringOrNull(attributes.signing_date)
    && isStringOrNull(attributes.comments_close_on)
    && isStringOrNull(attributes.abstract)
    && isStringOrNull(attributes.action)
    && isStringArrayOrNull(attributes.agency_names)
    && isStringOrNull(attributes.citation)
    && isStringArrayOrNull(attributes.docket_ids)
    && (attributes.cfr_references === null || Array.isArray(attributes.cfr_references))
    && typeof attributes.html_url === "string"
    && isStringOrNull(attributes.pdf_url);
}

function isDocumentPage(value: unknown): value is DocumentPage {
  if (!isRecord(value) || !isRecord(value.links) || !isRecord(value.meta) || !Array.isArray(value.data)) return false;
  const { links, meta } = value;
  if (links.next !== null && typeof links.next !== "string") return false;
  if (typeof meta.request_id !== "string" || !isRecord(meta.page) || !isRecord(meta.ingest)) return false;
  if (typeof meta.page.size !== "number" || typeof meta.page.hasMore !== "boolean") return false;

  const ingest = meta.ingest;
  if (!isStringOrNull(ingest.last_successful_at)) return false;
  const latestRun = ingest.latest_run;
  return (latestRun === null || (isRecord(latestRun)
    && typeof latestRun.status === "string"
    && isStringOrNull(latestRun.completion_reason)
    && typeof latestRun.started_at === "string"
    && isStringOrNull(latestRun.finished_at)))
    && value.data.every(isDocumentResource);
}

function responseRequestId(value: unknown): string | null {
  if (!isRecord(value) || !isRecord(value.meta) || typeof value.meta.request_id !== "string") return null;
  return value.meta.request_id;
}

function apiError(payload: unknown, status: number): DocumentLoadError {
  const requestId = responseRequestId(payload);
  const firstError = isRecord(payload) && Array.isArray(payload.errors) ? payload.errors[0] : null;
  if (!isRecord(firstError) || !isDocumentApiErrorCode(firstError.code)) {
    return new DocumentLoadError("INVALID_RESPONSE", "", status, requestId);
  }

  const message = typeof firstError.detail === "string" ? firstError.detail : "Your search or filters are invalid.";
  return new DocumentLoadError(firstError.code, message, status, requestId);
}

async function fetchPage(url: string, signal: AbortSignal): Promise<DocumentPage> {
  let response: Response;
  try {
    response = await fetch(url, { headers: { Accept: "application/vnd.api+json" }, signal });
  } catch (error) {
    if (signal.aborted) throw error;
    throw new DocumentLoadError("NETWORK_ERROR", "");
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch (error) {
    if (signal.aborted) throw error;
    throw new DocumentLoadError("INVALID_RESPONSE", "", response.status);
  }

  if (!response.ok) throw apiError(payload, response.status);
  if (!isDocumentPage(payload)) {
    throw new DocumentLoadError("INVALID_RESPONSE", "", response.status, responseRequestId(payload));
  }
  return payload;
}

function Detail({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="grid grid-cols-[120px_1fr] gap-4 border-b border-border py-3.5 text-sm last:border-0"><dt className="text-muted-foreground">{label}</dt><dd className="m-0 break-words font-medium text-foreground">{children || "—"}</dd></div>;
}

export function DocumentLibrary() {
  const [query, setQuery] = useQueryState("filter[q]", parseAsString.withDefault(""));
  const [dateFrom, setDateFrom] = useQueryState("filter[publication_date][gte]", parseAsString.withDefault(""));
  const [dateTo, setDateTo] = useQueryState("filter[publication_date][lte]", parseAsString.withDefault(""));
  const [sort, setSort] = useQueryState("sort", parseAsString.withDefault("-publication_date"));
  const [draft, setDraft] = useState(query);
  const [selected, setSelected] = useState<DocumentResource | null>(null);

  useEffect(() => setDraft(query), [query]);
  useEffect(() => {
    if (draft === query) return;
    const timeout = window.setTimeout(() => void setQuery(draft.trim()), 300);
    return () => window.clearTimeout(timeout);
  }, [draft, query, setQuery]);

  const apiUrl = useMemo(() => makeApiUrl(query, dateFrom, dateTo, sort), [query, dateFrom, dateTo, sort]);
  const documents = useInfiniteQuery({
    queryKey: ["documents", query, dateFrom, dateTo, sort],
    initialPageParam: apiUrl,
    queryFn: ({ pageParam, signal }) => fetchPage(pageParam, signal),
    getNextPageParam: (page) => page.links.next ?? undefined,
  });
  const rows = documents.data?.pages.flatMap((page) => page.data) ?? [];
  const freshness = documents.data?.pages[0]?.meta.ingest;
  const latestRun = freshness?.latest_run;
  const freshnessNote = latestRun?.status === "partial"
    ? "Latest run stopped at the source result limit."
    : latestRun?.status === "failed"
    ? "Latest run failed; showing the last successful ingest."
    : latestRun?.status === "running"
    ? "An ingest run is in progress."
    : null;
  const activePreset = dateFrom === localDate(6) && dateTo === localDate() ? "7d"
    : dateFrom === localDate(29) && dateTo === localDate() ? "30d"
    : "custom";

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void setQuery(draft.trim());
  }

  function setPreset(days: 7 | 30) {
    void Promise.all([setDateFrom(localDate(days - 1)), setDateTo(localDate())]);
  }

  function setColumnSort(field: (typeof sortColumns)[number]["key"]) {
    const currentField = sort.replace(/^-/, "");
    const direction = currentField === field && !sort.startsWith("-") ? "desc" : "asc";
    void setSort(direction === "desc" ? `-${field}` : field);
  }

  function resetSearchAndFilters() {
    setDraft("");
    void Promise.all([setQuery(""), setDateFrom(""), setDateTo(""), setSort("-publication_date")]);
  }

  const empty = !documents.isPending && !documents.isError && rows.length === 0;
  const errorRequest = documents.error instanceof DocumentLoadError ? documents.error : null;
  const errorTitle = errorRequest?.code === "INVALID_QUERY" ? "Check your search and filters." : "We couldn’t load the EPA rules.";
  const currentDocument = selected?.attributes;
  const cfrReferences = currentDocument?.cfr_references?.map((value) => {
    if (typeof value === "string") return value;
    if (value && typeof value === "object") return Object.values(value).filter((part) => typeof part === "string").join(" · ");
    return "";
  }).filter(Boolean).join(", ");

  return (
    <main className="min-h-screen bg-background text-foreground">
      <header className="flex h-16 items-center justify-between border-b border-border px-6 lg:px-12">
        <a className="inline-flex items-center gap-2.5 text-lg font-extrabold tracking-[-.06em] text-foreground no-underline" href="/" aria-label="Maiven home">
          <span className="relative inline-block size-5" aria-hidden="true"><i className="absolute bottom-0 left-0 size-2 rotate-[-35deg] rounded-[3px] bg-primary" /><i className="absolute left-[7px] top-[6px] size-2 rotate-[-35deg] rounded-[3px] bg-[#8068d8]" /><i className="absolute right-0 top-0 size-2 rotate-[-35deg] rounded-[3px] bg-[#58bca9]" /></span>
          maiven
        </a>
      </header>

      <section className="border-b border-border bg-white px-6 py-10 lg:px-12 lg:py-12">
        <div className="mx-auto max-w-[1320px]">
          <h1 className="m-0 max-w-3xl text-3xl font-semibold leading-tight tracking-[-.045em] sm:text-4xl">EPA rules</h1>
          <p className="mb-0 mt-3 max-w-2xl text-sm leading-6 text-muted-foreground sm:text-base">Published in the Federal Register by the U.S. Environmental Protection Agency.</p>
          <p className="mb-0 mt-2 text-xs text-muted-foreground" aria-live="polite">
            Last synced: {formatTimestamp(freshness?.last_successful_at ?? null)}
            {freshnessNote ? ` · ${freshnessNote}` : ""}
          </p>
        </div>
      </section>

      <section className="mx-auto max-w-[1320px] px-4 py-8 sm:px-6 lg:px-12 lg:py-10" aria-label="EPA rules search and results">
        <div className="mb-6 space-y-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
            <form className="min-w-0 flex-1" onSubmit={submitSearch}>
              <label className="flex h-11 items-center gap-3 rounded-md border border-input bg-white px-3 focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/20">
                <Search className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                <span className="sr-only">Search EPA rule titles and summaries</span>
                <Input className="h-full border-0 bg-transparent px-0 shadow-none focus-visible:ring-0" value={draft} onChange={(event) => setDraft(event.target.value)} placeholder="Search EPA rules" />
                {draft && <Button type="button" variant="ghost" size="icon-xs" aria-label="Clear search" onClick={() => { setDraft(""); void setQuery(""); }}><X /></Button>}
              </label>
            </form>
            <div className="shrink-0 self-end pb-1 text-sm text-muted-foreground sm:self-auto"><span className="font-semibold tabular-nums text-foreground">{rows.length}</span> {rows.length === 1 ? "rule" : "rules"}{documents.hasNextPage ? " loaded" : ""}</div>
          </div>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-3 rounded-lg border border-border bg-white px-4 py-3">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <span className="text-xs font-semibold text-foreground">Publication date</span>
              <div className="inline-flex items-center rounded-md border border-border bg-background p-0.5" aria-label="Publication date shortcuts">
                <Button type="button" variant="ghost" size="sm" aria-pressed={activePreset === "7d"} className={activePreset === "7d" ? "h-7 bg-secondary text-secondary-foreground hover:bg-secondary" : "h-7 text-muted-foreground"} onClick={() => setPreset(7)}>7 days</Button>
                <span className="mx-0.5 h-5 w-px bg-border" aria-hidden="true" />
                <Button type="button" variant="ghost" size="sm" aria-pressed={activePreset === "30d"} className={activePreset === "30d" ? "h-7 bg-secondary text-secondary-foreground hover:bg-secondary" : "h-7 text-muted-foreground"} onClick={() => setPreset(30)}>30 days</Button>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-2 border-t border-border pt-3 sm:border-l sm:border-t-0 sm:pt-0 sm:pl-4" aria-label="Custom publication date range">
              <span className="mr-1 text-xs font-medium text-muted-foreground">Custom range</span>
              <label className="flex items-center gap-2 text-xs text-muted-foreground">From <Input aria-label="Publication date from" type="date" className="h-8 w-[132px] bg-background px-2 text-xs" value={dateFrom} onChange={(event) => void setDateFrom(event.target.value)} /></label>
              <label className="flex items-center gap-2 text-xs text-muted-foreground">To <Input aria-label="Publication date to" type="date" className="h-8 w-[132px] bg-background px-2 text-xs" value={dateTo} onChange={(event) => void setDateTo(event.target.value)} /></label>
            </div>
            {(query || dateFrom || dateTo) && <Button type="button" variant="link" size="sm" className="ml-auto h-7 px-0 text-xs text-muted-foreground" onClick={() => { setDraft(""); void Promise.all([setQuery(""), setDateFrom(""), setDateTo("")]); }}>Clear filters</Button>}
          </div>
        </div>

        <div className="overflow-hidden rounded-lg border border-border bg-white">
          <div className="overflow-x-auto" tabIndex={0} aria-label="Scrollable EPA rules results table">
            <Table className="min-w-[1300px] table-fixed">
              <colgroup><col className="w-[128px]" /><col className="w-[155px]" /><col className="w-[450px]" /><col className="w-[120px]" /><col className="w-[260px]" /><col className="w-[185px]" /></colgroup>
              <TableHeader className="bg-[#f6f4f1]">
                <TableRow className="hover:bg-transparent">
                  {sortColumns.map((column) => {
                    const active = sort.replace(/^-/, "") === column.key;
                    const Icon = active ? (sort.startsWith("-") ? ArrowDown : ArrowUp) : ArrowDownUp;
                    return <TableHead key={column.key} aria-sort={active ? (sort.startsWith("-") ? "descending" : "ascending") : "none"} className="h-11 px-4 text-[11px] font-semibold text-muted-foreground">
                      <button type="button" className="inline-flex items-center gap-1.5 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" onClick={() => setColumnSort(column.key)}>{column.label}<Icon className={active ? "size-3 text-primary" : "size-3 opacity-45"} /></button>
                    </TableHead>;
                  })}
                  <TableHead className="h-11 px-4 text-[11px] font-semibold text-muted-foreground">Last synced</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {documents.isPending && <TableRow><TableCell className="h-40 text-center text-sm text-muted-foreground" colSpan={6}>Loading EPA rules…</TableCell></TableRow>}
                {documents.isError && <TableRow><TableCell className="h-40 text-center text-sm text-destructive" colSpan={6}><strong className="mb-1 block text-foreground">{errorTitle}</strong><span>{documentErrorMessage(documents.error)}</span>{errorRequest?.requestId && <span className="mt-1 block text-xs text-muted-foreground">Reference: {errorRequest.requestId}</span>}<Button type="button" variant="outline" size="sm" className="mx-auto mt-3 block" onClick={() => errorRequest?.code === "INVALID_QUERY" ? resetSearchAndFilters() : void documents.refetch()}>{errorRequest?.code === "INVALID_QUERY" ? "Reset search and filters" : "Try again"}</Button></TableCell></TableRow>}
                {empty && <TableRow><TableCell className="h-40 text-center text-sm text-muted-foreground" colSpan={6}><strong className="mb-1 block text-foreground">No EPA rules match these filters.</strong>Try changing your search or publication dates.</TableCell></TableRow>}
                {rows.map((document) => {
                  const { attributes } = document;
                  return <TableRow key={document.id} onClick={() => setSelected(document)} className="cursor-pointer border-border/80 hover:bg-[#faf9f6] focus-within:bg-[#faf9f6]">
                    <TableCell className="w-[125px] px-4 py-4 text-sm text-muted-foreground">{formatDate(attributes.publication_date)}</TableCell>
                    <TableCell className="w-[150px] px-4 py-4 font-mono text-xs text-muted-foreground">{attributes.document_number}</TableCell>
                    <TableCell className="whitespace-normal px-4 py-4">
                      <button type="button" aria-label={`View details for ${attributes.title}`} className="flex max-w-full items-start gap-1 text-left text-sm font-semibold leading-5 text-foreground underline-offset-4 hover:text-primary hover:underline focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"><span>{attributes.title}</span><ChevronRight aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-muted-foreground" /></button>
                      {attributes.citation && <span className="mt-1 block text-xs leading-5 text-muted-foreground">{attributes.citation}</span>}
                    </TableCell>
                    <TableCell className="w-[126px] px-4 py-4"><Badge variant="secondary" className="rounded-md px-2 py-1 text-[11px] font-medium">{attributes.type}</Badge></TableCell>
                    <TableCell className="w-[250px] whitespace-normal px-4 py-4 text-sm leading-5 text-muted-foreground">{attributes.agency_names?.join(", ") || "—"}</TableCell>
                    <TableCell className="whitespace-nowrap px-4 py-4 text-xs tabular-nums text-muted-foreground">{formatTimestamp(freshness?.last_successful_at ?? null)}</TableCell>
                  </TableRow>;
                })}
              </TableBody>
            </Table>
          </div>
        </div>
        <div className="sr-only" aria-live="polite" aria-atomic="true">Sorted by {sort.replace(/^-/, "").replaceAll("_", " ")} in {sort.startsWith("-") ? "descending" : "ascending"} order.</div>

        <div className="flex min-h-[88px] justify-center py-6">
          {documents.hasNextPage
            ? <Button className="h-10 gap-2 border-border bg-white px-5 text-sm font-medium text-foreground shadow-none hover:border-ring hover:bg-white" variant="outline" type="button" disabled={documents.isFetchingNextPage} aria-label={documents.isFetchingNextPage ? "Loading more rules" : "Load more rules"} onClick={() => void documents.fetchNextPage()}>Load More<ArrowDown className="size-4 text-primary" /></Button>
            : !documents.isPending && !documents.isError && rows.length > 0 && <span className="pt-2 text-xs text-muted-foreground">You’re at the end of the list</span>}
        </div>
      </section>

      <footer className="mx-auto flex min-h-[72px] max-w-[1320px] items-center justify-between gap-4 border-t border-border px-6 text-xs text-muted-foreground max-sm:flex-wrap max-sm:py-5 lg:px-12">
        <span className="text-sm font-extrabold tracking-[-.05em] text-foreground">maiven<span className="text-primary">.</span></span>
        <span>We make policy simple, so you can act with confidence.</span>
        <a className="no-underline hover:text-foreground" href="https://www.federalregister.gov/" target="_blank" rel="noreferrer">Source: Federal Register <ArrowUpRight className="inline size-3.5" /></a>
      </footer>

      <Sheet open={!!selected} onOpenChange={(open) => { if (!open) setSelected(null); }}>
        {currentDocument && <SheetContent aria-describedby="document-detail-description" className="sm:max-w-[560px]">
          <SheetDismiss />
          <SheetHeader className="pr-16">
            <div><Badge variant="secondary" className="mb-3 rounded-md px-2 py-1 text-xs font-medium">{currentDocument.type}</Badge><SheetTitle>{currentDocument.title}</SheetTitle></div>
            <SheetDescription id="document-detail-description">{currentDocument.document_number}{currentDocument.citation ? ` · ${currentDocument.citation}` : ""}</SheetDescription>
          </SheetHeader>
          <SheetBody>
            {currentDocument.abstract && <section className="mb-7"><h3 className="mb-2 text-sm font-semibold">Summary</h3><p className="m-0 whitespace-pre-line text-sm leading-6 text-muted-foreground">{currentDocument.abstract}</p></section>}
            {currentDocument.action && <section className="mb-7"><h3 className="mb-2 text-sm font-semibold">Action</h3><p className="m-0 whitespace-pre-line text-sm leading-6 text-muted-foreground">{currentDocument.action}</p></section>}
            <section><h3 className="mb-1 text-sm font-semibold">Document details</h3><dl className="m-0">
              <Detail label="Agency">{currentDocument.agency_names?.join(", ")}</Detail>
              <Detail label="Published">{formatDate(currentDocument.publication_date)}</Detail>
              <Detail label="Last synced">{formatTimestamp(freshness?.last_successful_at ?? null)}</Detail>
              <Detail label="Effective">{formatDate(currentDocument.effective_on)}</Detail>
              <Detail label="Comments due">{formatDate(currentDocument.comments_close_on)}</Detail>
              <Detail label="Signing date">{formatDate(currentDocument.signing_date)}</Detail>
              <Detail label="Docket">{currentDocument.docket_ids?.join(", ")}</Detail>
              <Detail label="CFR references">{cfrReferences}</Detail>
            </dl></section>
          </SheetBody>
          <SheetFooter className="sm:justify-start">
            {currentDocument.pdf_url
              ? <><a className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground no-underline hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" href={currentDocument.pdf_url} target="_blank" rel="noreferrer"><FileText className="size-4" />View public PDF<ArrowUpRight className="size-4" /></a><a className="inline-flex h-10 items-center justify-center rounded-md px-4 text-sm font-medium text-foreground underline-offset-4 hover:bg-muted hover:underline" href={currentDocument.html_url} target="_blank" rel="noreferrer">Open on Federal Register<ArrowUpRight className="ml-1 size-4" /></a></>
              : <Button render={<a href={currentDocument.html_url} target="_blank" rel="noreferrer" />}>Open on Federal Register<ArrowUpRight /></Button>}
          </SheetFooter>
        </SheetContent>}
      </Sheet>
    </main>
  );
}
