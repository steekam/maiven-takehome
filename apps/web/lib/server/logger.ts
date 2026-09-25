import pino from "pino";

const otlpEndpoint = process.env.OTEL_EXPORTER_OTLP_LOGS_ENDPOINT
  ?? process.env.OTEL_EXPORTER_OTLP_ENDPOINT;

const transport = otlpEndpoint
  ? pino.transport({
      targets: [
        {
          target: "pino/file",
          options: { destination: 1 },
        },
        {
          target: "pino-opentelemetry-transport",
          level: "error",
          options: {
            resourceAttributes: {
              "service.name": process.env.OTEL_SERVICE_NAME ?? "maiven-web",
            },
          },
        },
      ],
    })
  : undefined;

export const logger = transport
  ? pino({ level: process.env.LOG_LEVEL ?? "info" }, transport)
  : pino({ level: process.env.LOG_LEVEL ?? "info" });
