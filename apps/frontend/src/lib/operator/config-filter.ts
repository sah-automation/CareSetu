// OPERATOR (#875): config secret-key filter utility for the Settings page.

export const SECRET_KEY_PATTERNS = [
  "key",
  "secret",
  "password",
  "token",
  "url",
] as const;

export function isSecretKey(key: string): boolean {
  const lower = key.toLowerCase();
  return SECRET_KEY_PATTERNS.some((pattern) => lower.includes(pattern));
}
