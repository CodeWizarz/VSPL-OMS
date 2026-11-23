"use client";
import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Cookies from "js-cookie";
import { getCurrentUser } from "@/lib/api";
import { resolveWorkspace } from "@/lib/workspaces";

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    const token = Cookies.get("access_token");
    if (token) {
      // Land each department on its own home screen (e.g. F1 -> My Work Queue);
      // everyone else, or any lookup failure, keeps the dashboard as before.
      getCurrentUser()
        .then((u) => router.replace(resolveWorkspace(u.role, u.department)?.home ?? "/dashboard"))
        .catch(() => router.replace("/dashboard"));
    } else {
      router.replace("/login");
    }
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-zinc-950 text-white">
      <div className="flex flex-col items-center gap-3">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
        <p className="text-xs text-zinc-400 font-medium">Loading VSPL SMES...</p>
      </div>
    </div>
  );
}
