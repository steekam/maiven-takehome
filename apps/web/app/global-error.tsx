"use client";

import { useEffect } from "react";
import { ErrorScreen } from "@/components/error-screen";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(JSON.stringify({
      level: "error",
      event: "global_render_failed",
      error_name: error.name,
      error_digest: error.digest ?? null,
    }));
  }, [error]);

  return (
    <html lang="en">
      <body>
        <ErrorScreen title="Maiven couldn’t open." description="A page error stopped the app from rendering. Try again or return to EPA rules." reference={error.digest} reset={reset} />
      </body>
    </html>
  );
}
