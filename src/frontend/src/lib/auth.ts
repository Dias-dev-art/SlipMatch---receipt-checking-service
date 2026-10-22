"use client";

import { useSyncExternalStore } from "react";

// JWT in memory + localStorage (hackathon setup, same as the Full Stack FastAPI Template).
const TOKEN_KEY = "waitly.token";

let memoryToken: string | null | undefined;
const listeners = new Set<() => void>();

function readToken(): string | null {
  if (memoryToken === undefined) {
    try {
      memoryToken = localStorage.getItem(TOKEN_KEY);
    } catch {
      memoryToken = null;
    }
  }
  return memoryToken;
}

export function getToken(): string | null {
  return typeof window === "undefined" ? null : readToken();
}

export function setToken(token: string | null) {
  memoryToken = token;
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    // Storage blocked (private mode): keep the in-memory token only.
  }
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key !== TOKEN_KEY) return;
    memoryToken = event.newValue;
    listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** `token` is `undefined` until the browser has been checked (server render, hydration). */
export function useToken(): string | null | undefined {
  return useSyncExternalStore(subscribe, readToken, () => undefined);
}
