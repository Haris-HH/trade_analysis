import fs from "fs";
import path from "path";
import { NextRequest, NextResponse } from "next/server";
import type { AlertMode, AlertSettings } from "@/lib/types";

const SETTINGS_PATH = path.join(process.cwd(), "data", "alert_settings.json");
const VALID_MODES: AlertMode[] = ["crypto", "stock", "both", "none"];

function readLocalSettings(): AlertSettings {
  try {
    const raw = fs.readFileSync(SETTINGS_PATH, "utf-8");
    const parsed = JSON.parse(raw);
    if (VALID_MODES.includes(parsed.alert_mode)) return parsed;
  } catch {
    // fall through to default
  }
  return { alert_mode: "both" };
}

export async function GET() {
  return NextResponse.json(readLocalSettings());
}

// Vercel's filesystem is read-only at runtime, so the change is persisted by
// committing data/alert_settings.json to GitHub via its Contents API. The
// GitHub Actions cron job (scripts/main.py) reads that committed file on its
// next scan; the push also triggers Vercel to redeploy with the new value.
export async function POST(req: NextRequest) {
  const token = process.env.GITHUB_TOKEN;
  const repo = process.env.GITHUB_REPO;
  const branch = process.env.GITHUB_BRANCH || "main";

  if (!token || !repo) {
    return NextResponse.json(
      { error: "Server is missing GITHUB_TOKEN / GITHUB_REPO — cannot persist the setting." },
      { status: 500 }
    );
  }

  let body: { alert_mode?: string };
  try {
    body = await req.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  const alertMode = body.alert_mode;
  if (!alertMode || !VALID_MODES.includes(alertMode as AlertMode)) {
    return NextResponse.json({ error: `alert_mode must be one of ${VALID_MODES.join(", ")}` }, { status: 400 });
  }

  const contentsUrl = `https://api.github.com/repos/${repo}/contents/data/alert_settings.json`;
  const headers = {
    Authorization: `Bearer ${token}`,
    Accept: "application/vnd.github+json",
    "Content-Type": "application/json",
  };

  try {
    const getResp = await fetch(`${contentsUrl}?ref=${branch}`, { headers, cache: "no-store" });
    if (!getResp.ok) {
      const text = await getResp.text();
      return NextResponse.json({ error: `GitHub lookup failed: ${getResp.status} ${text}` }, { status: 502 });
    }
    const existing = await getResp.json();

    const newContent: AlertSettings = { alert_mode: alertMode as AlertMode };
    const putResp = await fetch(contentsUrl, {
      method: "PUT",
      headers,
      body: JSON.stringify({
        message: `chore: set alert_mode=${alertMode} [skip ci]`,
        content: Buffer.from(JSON.stringify(newContent, null, 2) + "\n", "utf-8").toString("base64"),
        sha: existing.sha,
        branch,
      }),
    });

    if (!putResp.ok) {
      const text = await putResp.text();
      return NextResponse.json({ error: `GitHub commit failed: ${putResp.status} ${text}` }, { status: 502 });
    }

    return NextResponse.json(newContent);
  } catch (err) {
    return NextResponse.json({ error: `Unexpected error: ${(err as Error).message}` }, { status: 500 });
  }
}
