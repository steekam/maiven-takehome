import {ArrowDown, ArrowDownUp, ArrowUp, ChevronRight} from "lucide-react";
import {Badge} from "@/components/ui/badge";
import {Button} from "@/components/ui/button";
import {Table, TableBody, TableCell, TableHead, TableHeader, TableRow} from "@/components/ui/table";
import {documentErrorMessage} from "@/lib/documents/errors";
import {formatDate, formatTimestamp} from "@/lib/utils";
import {useDocumentLibrary} from "./provider";

const sortColumns = [
  {key: "publication_date", label: "Published"},
  {key: "document_number", label: "Document no."},
  {key: "title", label: "Title"},
  {key: "type", label: "Type"},
  {key: "agency", label: "Agency"},
] as const;

export function Results() {
  const {state, actions, meta} = useDocumentLibrary();
  const errorTitle = state.error?.code === "INVALID_QUERY" ? "Check your search and filters." : "We couldn’t load the EPA rules.";

  return <>
    <div className="overflow-hidden rounded-lg border border-border bg-white">
      <div className="overflow-x-auto" tabIndex={0} aria-label="Scrollable EPA rules results table">
        <Table className="table-auto">
          <TableHeader className="bg-[#f6f4f1]">
            <TableRow className="hover:bg-transparent">
              {sortColumns.map((column) => {
                const active = state.sort.replace(/^-/, "") === column.key;
                const Icon = active ? (state.sort.startsWith("-") ? ArrowDown : ArrowUp) : ArrowDownUp;
                return <TableHead key={column.key}
                                  aria-sort={active ? (state.sort.startsWith("-") ? "descending" : "ascending") : "none"}
                                  className="h-11 px-4 text-[11px] font-semibold text-muted-foreground">
                  <button type="button"
                          className="inline-flex items-center gap-1.5 hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                          onClick={() => actions.sortBy(column.key)}>{column.label}<Icon
                    className={active ? "size-3 text-primary" : "size-3 opacity-45"}/></button>
                </TableHead>;
              })}
              <TableHead className="h-11 px-4 text-[11px] font-semibold text-muted-foreground">Last synced</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {state.isPending &&
              <TableRow><TableCell className="h-40 text-center text-sm text-muted-foreground" colSpan={6}>Loading EPA
                rules…</TableCell></TableRow>}
            {state.isError && <TableRow><TableCell className="h-40 text-center text-sm text-destructive" colSpan={6}>
              <strong className="mb-1 block text-foreground">{errorTitle}</strong>
              <span>{documentErrorMessage(state.error)}</span>
              {state.error?.requestId &&
                <span className="mt-1 block text-xs text-muted-foreground">Reference: {state.error.requestId}</span>}
              <Button type="button" variant="outline" size="sm" className="mx-auto mt-3 block"
                      onClick={actions.retry}>{state.error?.code === "INVALID_QUERY" ? "Reset search and filters" : "Try again"}</Button>
            </TableCell></TableRow>}
            {state.isEmpty &&
              <TableRow><TableCell className="h-40 text-center text-sm text-muted-foreground" colSpan={6}><strong
                className="mb-1 block text-foreground">No EPA rules match these filters.</strong>Try changing your
                search or publication dates.</TableCell></TableRow>}
            {state.results.map((document) => {
              const {attributes} = document;
              return <TableRow key={document.id} onClick={() => actions.selectDocument(document)}
                               className="cursor-pointer border-border/80 hover:bg-[#faf9f6] focus-within:bg-[#faf9f6]">
                <TableCell className="px-4 py-4 text-sm text-muted-foreground">{formatDate(attributes.publication_date)}</TableCell>
                <TableCell className="px-4 py-4 font-mono text-xs text-muted-foreground">{attributes.document_number}</TableCell>
                <TableCell className="whitespace-normal px-4 py-4">
                  <button type="button" aria-label={`View details for ${attributes.title}`}
                          className="flex max-w-full items-start gap-1 text-left text-sm font-semibold leading-5 text-foreground underline-offset-4 hover:text-primary hover:underline focus-visible:rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring">
                    <span>{attributes.title}</span><ChevronRight aria-hidden="true"
                                                                 className="mt-0.5 size-4 shrink-0 text-muted-foreground"/>
                  </button>
                  {attributes.citation &&
                    <span className="mt-1 block text-xs leading-5 text-muted-foreground">{attributes.citation}</span>}
                </TableCell>
                <TableCell className="px-4 py-4"><Badge variant="secondary"
                                                         className="rounded-md px-2 py-1 text-[11px] font-medium">{attributes.type}</Badge></TableCell>
                <TableCell className="whitespace-normal px-4 py-4 text-sm leading-5 text-muted-foreground">{attributes.agency_names?.join(", ") || "—"}</TableCell>
                <TableCell
                  className="whitespace-nowrap px-4 py-4 text-xs tabular-nums text-muted-foreground">{formatTimestamp(meta.lastSuccessfulAt)}</TableCell>
              </TableRow>;
            })}
          </TableBody>
        </Table>
      </div>
    </div>
    <div className="sr-only" aria-live="polite" aria-atomic="true">Sorted
      by {state.sort.replace(/^-/, "").replaceAll("_", " ")} in {state.sort.startsWith("-") ? "descending" : "ascending"} order.
    </div>
  </>;
}

export function LoadMore() {
  const {state, actions} = useDocumentLibrary();
  return <div className="flex min-h-[88px] justify-center py-6">
    {state.hasNextPage
      ? <Button
        className="h-10 gap-2 border-border bg-white px-5 text-sm font-medium text-foreground shadow-none hover:border-ring hover:bg-white"
        variant="outline" type="button" disabled={state.isFetchingNextPage}
        aria-label={state.isFetchingNextPage ? "Loading more rules" : "Load more rules"} onClick={actions.loadMore}>Load
        More<ArrowDown className="size-4 text-primary"/></Button>
      : !state.isPending && !state.isError && state.results.length > 0 &&
      <span className="pt-2 text-xs text-muted-foreground">You’re at the end of the list</span>}
  </div>;
}
