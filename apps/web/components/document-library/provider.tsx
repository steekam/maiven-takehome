"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import { createContext, use, useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { parseAsString, useQueryState } from "nuqs";
import type { DocumentResource } from "@/lib/documents/contracts";
import { DocumentLoadError } from "@/lib/documents/errors";
import type { DocumentSortField } from "@/lib/documents/query";
import { localDate } from "@/lib/utils";
import { fetchPage, makeApiUrl } from "./data";

type DatePreset = "7d" | "30d" | "custom";

type DocumentLibraryState = {
  query: string;
  draft: string;
  dateFrom: string;
  dateTo: string;
  sort: string;
  results: DocumentResource[];
  isPending: boolean;
  isError: boolean;
  isEmpty: boolean;
  error: DocumentLoadError | null;
  hasNextPage: boolean;
  isFetchingNextPage: boolean;
  selected: DocumentResource | null;
  activePreset: DatePreset;
};

type DocumentLibraryActions = {
  updateDraft: (value: string) => void;
  submitSearch: (event: FormEvent<HTMLFormElement>) => void;
  clearSearch: () => void;
  setDateFrom: (value: string) => void;
  setDateTo: (value: string) => void;
  setPreset: (days: 7 | 30) => void;
  sortBy: (field: DocumentSortField) => void;
  clearFilters: () => void;
  resetSearchAndFilters: () => void;
  selectDocument: (document: DocumentResource) => void;
  closeDetails: () => void;
  loadMore: () => void;
  retry: () => void;
};

type DocumentLibraryMeta = {
  resultCount: number;
  lastSuccessfulAt: string | null;
  freshnessNote: string | null;
};

type DocumentLibraryContextValue = {
  state: DocumentLibraryState;
  actions: DocumentLibraryActions;
  meta: DocumentLibraryMeta;
};

const DocumentLibraryContext = createContext<DocumentLibraryContextValue | null>(null);

export function useDocumentLibrary() {
  const value = use(DocumentLibraryContext);
  if (!value) throw new Error("Document library components must be inside DocumentLibrary.Provider.");
  return value;
}

export function DocumentLibraryProvider({ children }: { children: ReactNode }) {
  const [query, setQuery] = useQueryState("filter[q]", parseAsString.withDefault(""));
  const [dateFrom, setDateFromQuery] = useQueryState("filter[publication_date][gte]", parseAsString.withDefault(""));
  const [dateTo, setDateToQuery] = useQueryState("filter[publication_date][lte]", parseAsString.withDefault(""));
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
  const results = documents.data?.pages.flatMap((page) => page.data) ?? [];
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
  const error = documents.error instanceof DocumentLoadError ? documents.error : null;

  const state: DocumentLibraryState = {
    query,
    draft,
    dateFrom,
    dateTo,
    sort,
    results,
    isPending: documents.isPending,
    isError: documents.isError,
    isEmpty: !documents.isPending && !documents.isError && results.length === 0,
    error,
    hasNextPage: !!documents.hasNextPage,
    isFetchingNextPage: documents.isFetchingNextPage,
    selected,
    activePreset,
  };

  function resetSearchAndFilters() {
    setDraft("");
    void Promise.all([setQuery(""), setDateFromQuery(""), setDateToQuery(""), setSort("-publication_date")]);
  }

  const actions: DocumentLibraryActions = {
    updateDraft: setDraft,
    submitSearch(event) {
      event.preventDefault();
      void setQuery(draft.trim());
    },
    clearSearch() {
      setDraft("");
      void setQuery("");
    },
    setDateFrom(value) {
      void setDateFromQuery(value);
    },
    setDateTo(value) {
      void setDateToQuery(value);
    },
    setPreset(days) {
      void Promise.all([setDateFromQuery(localDate(days - 1)), setDateToQuery(localDate())]);
    },
    sortBy(field) {
      const currentField = sort.replace(/^-/, "");
      const direction = currentField === field && !sort.startsWith("-") ? "desc" : "asc";
      void setSort(direction === "desc" ? `-${field}` : field);
    },
    clearFilters() {
      setDraft("");
      void Promise.all([setQuery(""), setDateFromQuery(""), setDateToQuery("")]);
    },
    resetSearchAndFilters,
    selectDocument: setSelected,
    closeDetails() {
      setSelected(null);
    },
    loadMore() {
      void documents.fetchNextPage();
    },
    retry() {
      if (error?.code === "INVALID_QUERY") resetSearchAndFilters();
      else void documents.refetch();
    },
  };

  const meta: DocumentLibraryMeta = {
    resultCount: results.length,
    lastSuccessfulAt: freshness?.last_successful_at ?? null,
    freshnessNote,
  };

  return <DocumentLibraryContext value={{ state, actions, meta }}>{children}</DocumentLibraryContext>;
}
