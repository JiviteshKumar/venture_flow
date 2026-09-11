import { lazy, type ComponentType } from "react";

/**
 * `React.lazy` for a page, surviving a redeploy.
 *
 * Splitting the pages into their own files (see App.tsx) creates a failure the
 * single bundle never had. Every build names its files by content hash, and a
 * deploy replaces them. A tab opened before the deploy still holds the old
 * entry file, which asks for the old `Analysis-<hash>.js` the first time the
 * user navigates there -- and that file no longer exists. The import rejects,
 * and the root ErrorBoundary replaces the whole UI with "Something went wrong"
 * for a problem that one reload fixes.
 *
 * So a failed page import reloads the tab once, which fetches the new entry
 * and the new file names. The sessionStorage flag stops a genuinely broken
 * deploy from reloading forever: the second failure in a row is rethrown and
 * reaches the ErrorBoundary, with the real error attached.
 */
const RELOAD_FLAG = "vf:page-chunk-reloaded";

function readFlag(): boolean {
  try {
    return sessionStorage.getItem(RELOAD_FLAG) === "1";
  } catch {
    return false;
  }
}

function writeFlag(value: boolean): void {
  try {
    if (value) sessionStorage.setItem(RELOAD_FLAG, "1");
    else sessionStorage.removeItem(RELOAD_FLAG);
  } catch {
    // Storage blocked (private mode, site data disabled): no loop guard is
    // possible, so the error is rethrown below instead of reloading.
  }
}

export function lazyPage<T extends ComponentType<object>>(load: () => Promise<{ default: T }>) {
  return lazy(async () => {
    try {
      const page = await load();
      writeFlag(false);
      return page;
    } catch (error) {
      if (!readFlag()) {
        writeFlag(true);
        if (readFlag()) {
          window.location.reload();
          // Keep Suspense showing its fallback until the reload takes over.
          return new Promise<{ default: T }>(() => {});
        }
      }
      throw error;
    }
  });
}
