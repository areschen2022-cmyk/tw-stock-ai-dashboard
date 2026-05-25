const GITHUB_OWNER = "areschen2022-cmyk";
const GITHUB_REPO = "tw-stock-ai-dashboard";
const GITHUB_WORKFLOW = "daily.yml";
const GITHUB_REF = "main";

const CRON_TASKS = {
  "30 20 * * 0-4": "dashboard",
  "0 21 * * 0-4": "dashboard",
  "20 23 * * 0-4": "telegram",
  "35 23 * * 0-4": "telegram",
  "50 23 * * 0-4": "telegram",
  "5 0 * * 1-5": "telegram",
};

function toTaipeiIso(timestamp) {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Taipei",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  })
    .formatToParts(new Date(timestamp))
    .reduce((acc, part) => {
      acc[part.type] = part.value;
      return acc;
    }, {});
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}:${parts.second}+08:00`;
}

async function dispatchWorkflow(task, env, metadata = {}) {
  if (!env.GITHUB_TOKEN) {
    throw new Error("Missing GITHUB_TOKEN Worker secret");
  }

  const response = await fetch(
    `https://api.github.com/repos/${GITHUB_OWNER}/${GITHUB_REPO}/actions/workflows/${GITHUB_WORKFLOW}/dispatches`,
    {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        "Content-Type": "application/json",
        "User-Agent": "tw-stock-ai-cloudflare-scheduler",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({
        ref: GITHUB_REF,
        inputs: {
          task,
          send_telegram: task === "telegram" ? "true" : "false",
          scheduled_at_taipei: metadata.scheduledAtTaipei || "",
          scheduler: metadata.scheduler || "cloudflare-worker",
          scheduler_cron: metadata.cron || "",
        },
      }),
    },
  );

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`GitHub workflow_dispatch failed: ${response.status} ${body}`);
  }
}

async function handleCron(cron, env, scheduledTime) {
  const task = CRON_TASKS[cron];
  if (!task) {
    throw new Error(`No task mapped for cron: ${cron}`);
  }
  const scheduledAtTaipei = toTaipeiIso(scheduledTime);
  await dispatchWorkflow(task, env, { cron, scheduledAtTaipei, scheduler: "cloudflare-worker" });
  return { ok: true, task, cron, scheduled_at_taipei: scheduledAtTaipei };
}

async function handleRequest(request, env) {
  const url = new URL(request.url);
  if (url.pathname === "/health") {
    return Response.json({ ok: true, service: "tw-stock-ai-scheduler" });
  }

  if (url.pathname === "/dispatch") {
    if (env.DISPATCH_SECRET) {
      const secret = request.headers.get("x-dispatch-secret") || url.searchParams.get("secret");
      if (secret !== env.DISPATCH_SECRET) {
        return Response.json({ ok: false, error: "unauthorized" }, { status: 401 });
      }
    }

    const task = url.searchParams.get("task");
    if (!["dashboard", "telegram", "all"].includes(task)) {
      return Response.json({ ok: false, error: "task must be dashboard, telegram, or all" }, { status: 400 });
    }

    const scheduledAtTaipei = url.searchParams.get("scheduled_at_taipei") || "";
    await dispatchWorkflow(task, env, {
      scheduledAtTaipei,
      scheduler: "cloudflare-worker-http",
      cron: "manual-http",
    });
    return Response.json({ ok: true, task, scheduled_at_taipei: scheduledAtTaipei });
  }

  return Response.json({ ok: false, error: "not found" }, { status: 404 });
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(handleCron(event.cron, env, event.scheduledTime));
  },

  async fetch(request, env) {
    try {
      return await handleRequest(request, env);
    } catch (error) {
      return Response.json({ ok: false, error: String(error.message || error) }, { status: 500 });
    }
  },
};
