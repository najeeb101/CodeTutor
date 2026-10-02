// localStorage can throw (private windows, blocked site data) or be missing (server render).
// These helpers never throw: a failure just means "nothing stored".

export function readStored(key: string): string | null {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function writeStored(key: string, value: string | null): void {
  try {
    if (value === null) window.localStorage.removeItem(key);
    else window.localStorage.setItem(key, value);
  } catch {
    // nothing to do: the value is just not remembered
  }
}
