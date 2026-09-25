export const documentApiErrorCodes = [
  "INVALID_QUERY",
  "NOT_ACCEPTABLE",
  "DATABASE_UNAVAILABLE",
  "DATABASE_CONFIGURATION_ERROR",
  "INTERNAL_SERVER_ERROR",
] as const;

export type DocumentApiErrorCode = (typeof documentApiErrorCodes)[number];
export type DocumentLoadErrorCode = DocumentApiErrorCode | "NETWORK_ERROR" | "INVALID_RESPONSE";

export class DocumentLoadError extends Error {
  readonly code: DocumentLoadErrorCode;
  readonly status: number | null;
  readonly requestId: string | null;
  readonly retryable: boolean;

  constructor(
    code: DocumentLoadErrorCode,
    message: string,
    status: number | null = null,
    requestId: string | null = null,
  ) {
    super(message);
    this.name = "DocumentLoadError";
    this.code = code;
    this.status = status;
    this.requestId = requestId;
    this.retryable = code === "DATABASE_UNAVAILABLE" || code === "NETWORK_ERROR";
  }
}

export function documentErrorMessage(error: unknown): string {
  if (!(error instanceof DocumentLoadError)) return "We couldn’t load the EPA rules. Try again.";

  switch (error.code) {
    case "INVALID_QUERY":
      return error.message;
    case "NOT_ACCEPTABLE":
      return "This request format isn’t supported.";
    case "DATABASE_UNAVAILABLE":
      return "The document service is temporarily unavailable. Try again shortly.";
    case "DATABASE_CONFIGURATION_ERROR":
      return "The document service is unavailable. Try again later.";
    case "INTERNAL_SERVER_ERROR":
      return "Something went wrong while loading EPA rules.";
    case "NETWORK_ERROR":
      return "We couldn’t reach the service. Check your connection and try again.";
    case "INVALID_RESPONSE":
      return "The service returned a response we couldn’t read.";
  }
}
