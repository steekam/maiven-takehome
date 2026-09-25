import { Suspense } from "react";
import { DocumentLibrary } from "@/components/document-library";

export default function Home() {
  return <Suspense fallback={<main className="min-h-screen bg-background" />}><DocumentLibrary /></Suspense>;
}
