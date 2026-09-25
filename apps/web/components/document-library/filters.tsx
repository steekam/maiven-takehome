import {Search as SearchIcon, X} from "lucide-react";
import {Button} from "@/components/ui/button";
import {Input} from "@/components/ui/input";
import {useDocumentLibrary} from "./provider";

export function Search() {
  const {state, actions} = useDocumentLibrary();
  return <form className="min-w-0 flex-1" onSubmit={actions.submitSearch}>
    <label
      className="flex h-11 items-center gap-3 rounded-md border border-input bg-white px-3 focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/20">
      <SearchIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden="true"/>
      <span className="sr-only">Search EPA rule titles and summaries</span>
      <Input className="h-full border-0 bg-transparent px-0 shadow-none focus-visible:ring-0" value={state.draft}
             onChange={(event) => actions.updateDraft(event.target.value)} placeholder="Search EPA rules"/>
      {state.draft && <Button type="button" variant="ghost" size="icon-xs" aria-label="Clear search"
                              onClick={actions.clearSearch}><X/></Button>}
    </label>
  </form>;
}

export function ResultCount() {
  const {state, meta} = useDocumentLibrary();
  return <div className="shrink-0 self-end pb-1 text-sm text-muted-foreground sm:self-auto">
    <span
      className="font-semibold tabular-nums text-foreground">{meta.resultCount}</span> {meta.resultCount === 1 ? "rule" : "rules"}{state.hasNextPage ? " loaded" : ""}
  </div>;
}

export function PublicationPresets() {
  const {state, actions} = useDocumentLibrary();
  return <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
    <span className="text-xs font-semibold text-foreground">Publication date</span>
    <div className="inline-flex items-center rounded-md border border-border bg-background p-0.5"
         aria-label="Publication date shortcuts">
      <Button type="button" variant="ghost" size="sm" aria-pressed={state.activePreset === "7d"}
              className={state.activePreset === "7d" ? "h-7 bg-secondary text-secondary-foreground hover:bg-secondary" : "h-7 text-muted-foreground"}
              onClick={() => actions.setPreset(7)}>7 days</Button>
      <span className="mx-0.5 h-5 w-px bg-border" aria-hidden="true"/>
      <Button type="button" variant="ghost" size="sm" aria-pressed={state.activePreset === "30d"}
              className={state.activePreset === "30d" ? "h-7 bg-secondary text-secondary-foreground hover:bg-secondary" : "h-7 text-muted-foreground"}
              onClick={() => actions.setPreset(30)}>30 days</Button>
    </div>
  </div>;
}

export function PublicationDateRange() {
  const {state, actions} = useDocumentLibrary();
  return <div
    className="flex flex-wrap items-center gap-x-2 gap-y-2 border-t border-border pt-3 sm:border-l sm:border-t-0 sm:pt-0 sm:pl-4"
    aria-label="Custom publication date range">
    <span className="mr-1 text-xs font-medium text-muted-foreground">Custom range</span>
    <label className="flex items-center gap-2 text-xs text-muted-foreground">From <Input
      aria-label="Publication date from" type="date" className="h-8 w-[132px] bg-background px-2 text-xs"
      value={state.dateFrom} onChange={(event) => actions.setDateFrom(event.target.value)}/></label>
    <label className="flex items-center gap-2 text-xs text-muted-foreground">To <Input aria-label="Publication date to"
                                                                                       type="date"
                                                                                       className="h-8 w-[132px] bg-background px-2 text-xs"
                                                                                       value={state.dateTo}
                                                                                       onChange={(event) => actions.setDateTo(event.target.value)}/></label>
  </div>;
}

export function ClearFilters() {
  const {state, actions} = useDocumentLibrary();
  if (!state.query && !state.dateFrom && !state.dateTo) return null;
  return <Button type="button" variant="link" size="sm" className="ml-auto h-7 px-0 text-xs text-muted-foreground"
                 onClick={actions.clearFilters}>Clear filters</Button>;
}

export function PublicationFilters() {
  return <div
    className="flex flex-wrap items-center gap-x-4 gap-y-3 rounded-lg border border-border bg-white px-4 py-3">
    <PublicationPresets/>
    <PublicationDateRange/>
    <ClearFilters/>
  </div>;
}
