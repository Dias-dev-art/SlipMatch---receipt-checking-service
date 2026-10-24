"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

// A static export cannot redirect on the server, so the browser does it.
export default function Home() {
  const router = useRouter();
  useEffect(() => router.replace("/orders"), [router]);
  return null;
}
