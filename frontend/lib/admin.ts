"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError } from "./api";

export interface AdminMe {
  id: string;
  username: string;
  must_change_password: boolean;
}

/** Redirects to the login page unless an admin is logged in (and has set their own password). */
export function useAdmin(): AdminMe | null {
  const router = useRouter();
  const [me, setMe] = useState<AdminMe | null>(null);
  useEffect(() => {
    api<AdminMe>("/auth/me")
      .then((m) => {
        if (m.must_change_password) router.replace("/admin/login");
        else setMe(m);
      })
      .catch((e) => {
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) router.replace("/admin/login");
      });
  }, [router]);
  return me;
}

export async function logout() {
  await api("/auth/logout", { method: "POST" }).catch(() => undefined);
  window.location.href = "/admin/login";
}
