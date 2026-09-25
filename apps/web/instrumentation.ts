export async function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;

  const sharedEndpoint = process.env.OTEL_EXPORTER_OTLP_ENDPOINT;
  const hasTraceEndpoint = Boolean(
    process.env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT
      || sharedEndpoint
      || process.env.VERCEL_OTEL_ENDPOINTS,
  );
  const hasMetricsEndpoint = Boolean(
    process.env.OTEL_EXPORTER_OTLP_METRICS_ENDPOINT || sharedEndpoint,
  );
  if (!hasTraceEndpoint && !hasMetricsEndpoint) return;

  const { registerOTel } = await import("@vercel/otel");
  const metricReaders = hasMetricsEndpoint
    ? await Promise.all([
        import("@opentelemetry/exporter-metrics-otlp-http"),
        import("@opentelemetry/sdk-metrics"),
      ]).then(([{ OTLPMetricExporter }, { PeriodicExportingMetricReader }]) => [
        new PeriodicExportingMetricReader({
          exporter: new OTLPMetricExporter(),
          exportIntervalMillis: 10_000,
        }),
      ])
    : undefined;

  registerOTel({
    serviceName: process.env.OTEL_SERVICE_NAME ?? "maiven-web",
    ...(metricReaders ? { metricReaders } : {}),
    ...(!hasTraceEndpoint ? { spanProcessors: [] } : {}),
  });
}
