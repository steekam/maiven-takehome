import { existsSync } from "node:fs";
import { registerHooks } from "node:module";
import { extname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const webRoot = resolve(import.meta.dirname, "..");
const routeUrl = pathToFileURL(resolve(webRoot, "app/api/documents/route.ts")).href;
const documentReadUrl = pathToFileURL(resolve(webRoot, "lib/documents/read.ts")).href;
const readStubUrl = pathToFileURL(resolve(webRoot, "tests/stubs/document-read.mjs")).href;
const databaseStubUrl = pathToFileURL(resolve(webRoot, "tests/stubs/database.mjs")).href;
const serverOnlyStubUrl = pathToFileURL(resolve(webRoot, "tests/stubs/server-only.mjs")).href;

delete process.env.OTEL_EXPORTER_OTLP_ENDPOINT;
delete process.env.OTEL_EXPORTER_OTLP_LOGS_ENDPOINT;

function resolveSource(path) {
  if (existsSync(path)) return path;
  for (const extension of [".ts", ".tsx", ".mjs", ".js"]) {
    if (existsSync(`${path}${extension}`)) return `${path}${extension}`;
  }
  return null;
}

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === "server-only") {
      return { url: serverOnlyStubUrl, shortCircuit: true };
    }
    if (specifier === "@/lib/documents/read" && context.parentURL === routeUrl) {
      return { url: readStubUrl, shortCircuit: true };
    }
    if (specifier === "@/lib/server/db" && context.parentURL === documentReadUrl) {
      return { url: databaseStubUrl, shortCircuit: true };
    }
    if (specifier.startsWith("@/")) {
      const source = resolveSource(resolve(webRoot, specifier.slice(2)));
      if (source) return { url: pathToFileURL(source).href, shortCircuit: true };
    }
    if (specifier.startsWith(".") && context.parentURL && !extname(specifier)) {
      const target = fileURLToPath(new URL(specifier, context.parentURL));
      const source = resolveSource(target);
      if (source) return { url: pathToFileURL(source).href, shortCircuit: true };
    }
    return nextResolve(specifier, context);
  },
});
