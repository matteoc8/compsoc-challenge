"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, ApiError } from "./api";

export interface TeacherMe {
  id: string;
  username: string;
  must_change_password: boolean;
}

/** Redirects to the login page unless a teacher is logged in (and has set their own password). */
export function useTeacher(): TeacherMe | null {
  const router = useRouter();
  const [me, setMe] = useState<TeacherMe | null>(null);
  useEffect(() => {
    api<TeacherMe>("/auth/me")
      .then((m) => {
        if (m.must_change_password) router.replace("/teacher/login");
        else setMe(m);
      })
      .catch((e) => {
        if (e instanceof ApiError && (e.status === 401 || e.status === 403)) router.replace("/teacher/login");
      });
  }, [router]);
  return me;
}

export async function logout() {
  await api("/auth/logout", { method: "POST" }).catch(() => undefined);
  window.location.href = "/teacher/login";
}
