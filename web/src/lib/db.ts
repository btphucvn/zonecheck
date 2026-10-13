import "server-only";
import { AsyncLocalStorage } from "node:async_hooks";
import postgres from "postgres";

// The web only reads: every session is read-only with a statement timeout, so
// a slow query can never block the ETL writing to the same database.
//
// `"use cache"` scopes must not wait on promises created outside them, and a
// shared pool's queue is exactly that. So each cache fill runs inside
// `scoped()`, which gives it a client of its own; `sql` resolves to that client
// inside a scope and to the shared pool everywhere else (API routes).
//
// Opening a connection costs ~2 s over the SSH tunnel, so scope clients are not
// closed afterwards: a client that finished cleanly (nothing in flight) goes
// back on an idle list and the next scope takes it over exclusively, warm
// connections included. A client a scope gave up on (error, or `abandon()` after
// a timed-out query) still has work in flight and is closed instead.

function options(max: number): postgres.Options<Record<string, postgres.PostgresType>> {
  return {
    max,
    idle_timeout: 60,
    connect_timeout: Number(process.env.DB_CONNECT_TIMEOUT_S ?? 30),
    connection: {
      application_name: "zonecheck-web",
      default_transaction_read_only: true,
      statement_timeout: Number(process.env.DB_STATEMENT_TIMEOUT_MS ?? 15000),
    },
  };
}

function url(): string {
  const u = process.env.DATABASE_URL;
  if (!u) throw new Error("DATABASE_URL is not set. Copy web/.env.example to web/.env.local.");
  return u;
}

const globalForDb = globalThis as unknown as { __zcPool?: postgres.Sql };
const pool = () => (globalForDb.__zcPool ??= postgres(url(), options(Number(process.env.DB_POOL_MAX ?? 10))));
interface Scope { client: postgres.Sql; max: number; dirty: boolean }
const store = new AsyncLocalStorage<Scope>();
const IDLE_MAX = Number(process.env.DB_IDLE_CLIENTS ?? 4);
const idle: { client: postgres.Sql; max: number }[] = ((globalThis as { __zcIdle?: typeof idle }).__zcIdle ??= []);

/** Run `fn` with a client of its own (reused from the idle list when possible). Nested scopes get their own client too. */
export async function scoped<T>(fn: () => Promise<T>, max = 6): Promise<T> {
  const i = idle.findIndex((c) => c.max >= max);
  const scope: Scope = i >= 0 ? { ...idle.splice(i, 1)[0], dirty: false } : { client: postgres(url(), options(max)), max, dirty: false };
  try {
    return await store.run(scope, fn);
  } catch (e) {
    scope.dirty = true;
    throw e;
  } finally {
    if (!scope.dirty && idle.length < IDLE_MAX) idle.push({ client: scope.client, max: scope.max });
    else void scope.client.end({ timeout: 2 });
  }
}

/** Mark the current scope's client as having abandoned queries, so it is closed rather than reused. */
export function abandon(): void {
  const s = store.getStore();
  if (s) s.dirty = true;
}

const current = () => store.getStore()?.client ?? pool();

/** Tagged-template SQL bound to the current scope's client (or the shared pool). */
export const sql = new Proxy(function () {} as unknown as postgres.Sql, {
  apply: (_t, _this, args) => (current() as unknown as (...a: unknown[]) => unknown)(...args),
  get: (_t, prop) => {
    const c = current() as unknown as Record<string | symbol, unknown>;
    const v = c[prop];
    return typeof v === "function" ? (v as (...a: unknown[]) => unknown).bind(c) : v;
  },
});
