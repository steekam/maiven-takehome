"use client";

import { useEffect } from "react";
import { ErrorScreen } from "@/components/error-screen";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(JSON.stringify({
      level: "error",
      event: "route_render_failed",
      error_name: error.name,
      error_digest: error.digest ?? null,
    }));
  }, [error]);

  return <ErrorScreen title="This part of Maiven didn’t load." description="Try again to reload this view. Your search and filters remain in the URL." reference={error.digest} reset={reset} />;
}
