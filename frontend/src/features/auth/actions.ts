"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { z } from "zod";

import { apiClient, SESSION_COOKIE } from "@/lib/api/server";

const LoginSchema = z.object({ user_id: z.string().regex(/^[a-z0-9_]{1,64}$/) });

const SESSION_MAX_AGE_S = 12 * 3600;

function sessionToken(response: Response): string | null {
  for (const cookie of response.headers.getSetCookie()) {
    const [pair] = cookie.split(";");
    const index = pair.indexOf("=");
    if (pair.slice(0, index).trim() === SESSION_COOKIE) {
      const value = pair.slice(index + 1).trim().replace(/^"|"$/g, "");
      return value || null;
    }
  }
  return null;
}

/** Seeded user switcher (decision 4): FastAPI issues the signed session, and this passes
 * it on to the browser with the same attributes (plan 3.15). Works without JavaScript. */
export async function login(formData: FormData): Promise<void> {
  const parsed = LoginSchema.safeParse({ user_id: formData.get("user_id") });
  if (!parsed.success) redirect("/login?error=unknown_user");
  const api = await apiClient();
  const { response, error } = await api.POST("/api/v1/auth/login", { body: parsed.data });
  const token = error === undefined ? sessionToken(response) : null;
  if (!token) redirect(`/login?error=${response.status === 401 ? "unknown_user" : "unavailable"}`);
  const jar = await cookies();
  jar.set(SESSION_COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: SESSION_MAX_AGE_S,
    secure: process.env.COOKIE_SECURE === "true",
  });
  redirect("/");
}

/** Ends every session of this user on the API (and their live streams), then here. */
export async function logout(): Promise<void> {
  const api = await apiClient();
  await api.POST("/api/v1/auth/logout", { body: {} }).catch(() => undefined);
  const jar = await cookies();
  jar.delete(SESSION_COOKIE);
  redirect("/login");
}
