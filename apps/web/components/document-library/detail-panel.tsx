import { ArrowUpRight, FileText } from "lucide-react";
import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetBody, SheetContent, SheetDescription, SheetDismiss, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { formatDate, formatTimestamp } from "@/lib/utils";
import { formatCfrReferences } from "./data";
import { useDocumentLibrary } from "./provider";

function Detail({ label, children }: { label: string; children: ReactNode }) {
  return <div className="grid grid-cols-[120px_1fr] gap-4 border-b border-border py-3.5 text-sm last:border-0"><dt className="text-muted-foreground">{label}</dt><dd className="m-0 break-words font-medium text-foreground">{children || "—"}</dd></div>;
}

export function DetailPanel() {
  const { state, actions, meta } = useDocumentLibrary();
  const document = state.selected?.attributes;

  return <Sheet open={!!state.selected} onOpenChange={(open) => { if (!open) actions.closeDetails(); }}>
    {document && <SheetContent aria-describedby="document-detail-description" className="sm:max-w-[560px]">
      <SheetDismiss />
      <SheetHeader className="pr-16">
        <div><Badge variant="secondary" className="mb-3 rounded-md px-2 py-1 text-xs font-medium">{document.type}</Badge><SheetTitle>{document.title}</SheetTitle></div>
        <SheetDescription id="document-detail-description">{document.document_number}{document.citation ? ` · ${document.citation}` : ""}</SheetDescription>
      </SheetHeader>
      <SheetBody>
        {document.abstract && <section className="mb-7"><h3 className="mb-2 text-sm font-semibold">Summary</h3><p className="m-0 whitespace-pre-line text-sm leading-6 text-muted-foreground">{document.abstract}</p></section>}
        {document.action && <section className="mb-7"><h3 className="mb-2 text-sm font-semibold">Action</h3><p className="m-0 whitespace-pre-line text-sm leading-6 text-muted-foreground">{document.action}</p></section>}
        <section><h3 className="mb-1 text-sm font-semibold">Document details</h3><dl className="m-0">
          <Detail label="Agency">{document.agency_names?.join(", ")}</Detail>
          <Detail label="Published">{formatDate(document.publication_date)}</Detail>
          <Detail label="Last synced">{formatTimestamp(meta.lastSuccessfulAt)}</Detail>
          <Detail label="Effective">{formatDate(document.effective_on)}</Detail>
          <Detail label="Comments due">{formatDate(document.comments_close_on)}</Detail>
          <Detail label="Signing date">{formatDate(document.signing_date)}</Detail>
          <Detail label="Docket">{document.docket_ids?.join(", ")}</Detail>
          <Detail label="CFR references">{formatCfrReferences(document.cfr_references)}</Detail>
        </dl></section>
      </SheetBody>
      <SheetFooter className="sm:justify-start">
        {document.pdf_url
          ? <><a className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-primary px-4 text-sm font-medium text-primary-foreground no-underline hover:bg-primary/90 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" href={document.pdf_url} target="_blank" rel="noreferrer"><FileText className="size-4" />View public PDF<ArrowUpRight className="size-4" /></a><a className="inline-flex h-10 items-center justify-center rounded-md px-4 text-sm font-medium text-foreground underline-offset-4 hover:bg-muted hover:underline" href={document.html_url} target="_blank" rel="noreferrer">Open on Federal Register<ArrowUpRight className="ml-1 size-4" /></a></>
          : <Button render={<a href={document.html_url} target="_blank" rel="noreferrer" />}>Open on Federal Register<ArrowUpRight /></Button>}
      </SheetFooter>
    </SheetContent>}
  </Sheet>;
}
