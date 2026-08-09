"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

const POLL_INTERVAL_MS = 30_000;

export function AutoRefresh({ generatedAt }: { generatedAt: string }) {
  const router = useRouter();
  const currentRef = useRef(generatedAt);
  const [live, setLive] = useState(true);

  useEffect(() => {
    currentRef.current = generatedAt;
  }, [generatedAt]);

  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch(`/data/latest.json?t=${Date.now()}`, { cache: "no-store" });
        const data = await res.json();
        setLive(true);
        if (data.generated_at && data.generated_at !== currentRef.current) {
          router.refresh();
        }
      } catch {
        setLive(false);
      }
    };

    const id = setInterval(check, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, [router]);

  return (
    <span className="badge live-badge">
      <span className={`live-dot ${live ? "on" : "off"}`} />
      อัปเดตอัตโนมัติทุก 30 วิ
    </span>
  );
}
