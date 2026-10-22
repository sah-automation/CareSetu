// Shared helpers for the E2E suite (coding-standards §9.2: one source of
// truth). Reading the mock OTP, deriving an RFC 6238 TOTP code and reading
// the bootstrap operator's MFA facts are the same three needs in every spec
// that touches the auth surface - carrying a copy per spec made each change a
// multi-file edit and let the copies drift.

import { expect, type APIRequestContext } from "@playwright/test";
import { createHmac } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

/** The backend the E2E webServer boots (playwright.config.ts). */
export const BACKEND_BASE_URL = "http://localhost:8000";

/** The seeded bootstrap operator's phone, in the E.164 form the API speaks. */
export const BOOTSTRAP_OPERATOR_PHONE = "+919000000002";

export interface BootstrapSeedInfo {
  phone: string;
  totp_secret: string;
}

/** Where the backend boot stashes the bootstrap operator's MFA facts. */
export const BOOTSTRAP_SEED_INFO_PATH = path.join(
  process.cwd(),
  "apps",
  "backend",
  "var",
  "e2e-bootstrap-operator.json",
);

// The e2e backend boot writes the bootstrap operator's MFA facts here
// (scripts/e2e-backend.cjs). Read them at sign-in so a fresh boot always
// refreshes the attestation.
export function readBootstrapSeedInfo(): BootstrapSeedInfo {
  if (!fs.existsSync(BOOTSTRAP_SEED_INFO_PATH)) {
    throw new Error(
      `missing ${BOOTSTRAP_SEED_INFO_PATH} - restart the e2e backend boot so ` +
        "seed_demo.py stashes the bootstrap operator's MFA facts",
    );
  }
  return JSON.parse(
    fs.readFileSync(BOOTSTRAP_SEED_INFO_PATH, "utf8"),
  ) as BootstrapSeedInfo;
}

// ---- RFC 6238 TOTP, no external deps (node:crypto only) ----

function base32Decode(input: string): Buffer {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";
  const clean = input.toUpperCase().replace(/[\s=]/g, "");
  let out = Buffer.alloc(0);
  let buffer = 0n;
  let bits = 0n;
  for (const char of clean) {
    const index = alphabet.indexOf(char);
    if (index === -1) {
      throw new Error(`invalid base32 character ${JSON.stringify(char)}`);
    }
    buffer = (buffer << 5n) | BigInt(index);
    bits += 5n;
    if (bits >= 8n) {
      bits -= 8n;
      out = Buffer.concat([out, Buffer.from([Number(buffer >> bits) & 0xff])]);
      buffer &= (1n << bits) - 1n;
    }
  }
  return out;
}

/**
 * The code for the TOTP step `windowOffset` steps away from now (0 is the
 * current step). The offset is always explicit: the server accepts one step
 * of drift either side, so a caller that straddles a step boundary tries the
 * neighbours in turn.
 */
export function totpCode(secret: string, windowOffset: number): string {
  const counter = Math.floor(Date.now() / 1000 / 30) + windowOffset;
  const counterBytes = Buffer.alloc(8);
  counterBytes.writeBigUInt64BE(BigInt(counter));
  const digest = createHmac("sha1", base32Decode(secret))
    .update(counterBytes)
    .digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const binary =
    ((digest[offset] & 0x7f) << 24) |
    ((digest[offset + 1] << 16) |
      (digest[offset + 2] << 8) |
      digest[offset + 3]);
  return String(binary % 1_000_000).padStart(6, "0");
}

// ---- The mock OTP read-back ----

/**
 * The code the mock SMS provider last sent to `phone` (E.164), or null when
 * the phone holds no challenge. A challenge can already be spent when another
 * spec drove the same phone first, so a caller that only needs the code if
 * one exists reads it through this.
 */
export async function readMockOtp(
  request: APIRequestContext,
  phone: string,
): Promise<string | null> {
  const url = `${BACKEND_BASE_URL}/v1/auth/dev/otp?${new URLSearchParams({
    phone,
  })}`;
  const response = await request.get(url);
  expect(response.status(), "dev mock-OTP read-back should answer 200").toBe(
    200,
  );
  const body = (await response.json()) as { code: string | null };
  return body.code;
}

/** The mock OTP for `phone`, refusing when the provider sent no code. */
export async function requireMockOtp(
  request: APIRequestContext,
  phone: string,
): Promise<string> {
  const code = await readMockOtp(request, phone);
  expect(code, `mock SMS should have sent a code to ${phone}`).not.toBeNull();
  return code as string;
}
