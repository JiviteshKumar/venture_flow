import { useCallback, useEffect, useState } from "react";

/**
 * State that survives a reload, stored per-browser.
 *
 * Every read and write is wrapped, because `localStorage` is not merely
 * "sometimes empty" — accessing it *throws* in a private window with site data
 * blocked, and in some embedded webviews. An unguarded read there takes down
 * the component that called it, which is a poor trade for a convenience
 * feature.
 *
 * This is deliberately not a substitute for authentication. It remembers a
 * display name the user typed on this device; it establishes nothing about who
 * they are, and nothing in the app should treat it as identity.
 */
export function useLocalStorage<T>(
  key: string,
  initialValue: T,
): [T, (value: T) => void] {
  const [stored, setStored] = useState<T>(() => {
    try {
      const raw = window.localStorage.getItem(key);
      return raw === null ? initialValue : (JSON.parse(raw) as T);
    } catch {
      return initialValue;
    }
  });

  const setValue = useCallback(
    (value: T) => {
      setStored(value);
      try {
        window.localStorage.setItem(key, JSON.stringify(value));
      } catch {
        /* Storage unavailable or full: keep the in-memory value and move on. */
      }
    },
    [key],
  );

  // Keep two tabs in step. Without this, setting a display name in one tab
  // leaves the other showing the old one until it is reloaded.
  useEffect(() => {
    const onStorage = (event: StorageEvent) => {
      if (event.key !== key || event.newValue === null) return;
      try {
        setStored(JSON.parse(event.newValue) as T);
      } catch {
        /* Another tab wrote something we cannot parse; ignore it. */
      }
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [key]);

  return [stored, setValue];
}

export default useLocalStorage;
