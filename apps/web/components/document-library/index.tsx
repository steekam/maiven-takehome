"use client";

import { DetailPanel } from "./detail-panel";
import { ClearFilters, PublicationDateRange, PublicationFilters, PublicationPresets, ResultCount, Search } from "./filters";
import { DocumentLibraryProvider } from "./provider";
import { LoadMore, Results } from "./results";
import { Content, Footer, Hero, Masthead, PageFrame, SearchRow } from "./shell";

function DocumentLibraryRoot() {
  return <DocumentLibraryProvider>
    <PageFrame>
      <Masthead />
      <Hero />
      <Content>
        <div className="mb-6 space-y-3">
          <SearchRow>
            <Search />
            <ResultCount />
          </SearchRow>
          <PublicationFilters />
        </div>
        <Results />
        <LoadMore />
      </Content>
      <Footer />
      <DetailPanel />
    </PageFrame>
  </DocumentLibraryProvider>;
}

export const DocumentLibrary = Object.assign(DocumentLibraryRoot, {
  Provider: DocumentLibraryProvider,
  Frame: PageFrame,
  Masthead,
  Hero,
  Content,
  SearchRow,
  Search,
  ResultCount,
  PublicationFilters,
  PublicationPresets,
  PublicationDateRange,
  ClearFilters,
  Results,
  LoadMore,
  Footer,
  DetailPanel,
});
