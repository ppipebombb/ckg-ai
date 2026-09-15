import { http } from "./client";
import { AdminOut, TokenResponse, type Admin } from "./types";

export async function adminLogin(input: { email: string; password: string }) {
  const { data } = await http.post("/admin/auth/login", input);
  return TokenResponse.parse(data);
}

export async function adminMe(): Promise<Admin> {
  const { data } = await http.get("/admin/auth/me");
  return AdminOut.parse(data);
}

// Server-side revocation: denylists the presented token so it can't be reused
// after logout (the JWT is otherwise valid until its 24h exp). Best-effort —
// the caller clears local state regardless of the outcome.
export async function adminLogout(): Promise<void> {
  await http.post("/admin/auth/logout");
}
