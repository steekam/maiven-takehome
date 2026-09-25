import "server-only";
import { createDatabase } from "@maiven/db";

let database: ReturnType<typeof createDatabase> | undefined;

export class DatabaseConfigurationError extends Error {
  constructor() {
    super("DATABASE_URL is not configured.");
    this.name = "DatabaseConfigurationError";
  }
}

export function getDatabase() {
  const connectionString = process.env.DATABASE_URL;
  if (!connectionString) throw new DatabaseConfigurationError();
  database ??= createDatabase(connectionString);
  return database.db;
}
