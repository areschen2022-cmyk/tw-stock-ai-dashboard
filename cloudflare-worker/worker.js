const GITHUB_OWNER = "areschen2022-cmyk";
const GITHUB_REPO = "tw-stock-ai-dashboard";
const GITHUB_WORKFLOW = "daily.yml";
const GITHUB_REF = "main";

const CRON_TASKS = {
  "30 20 * * 0-4": "dashboard",
  "0 21 * * 0-4": "dashboard",
  "0 0 * * 1-5": "telegram",
  "15 0 * * 1-5": "telegram",
};

async function dispatchWorkflow(task, env) {
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
        },
      }),
    },
  );

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`GitHub workflow_dispatch failed: ${response.status} ${body}`);
  }
}

async function handleCron(cron, env) {
  const task = CRON_TASKS[cron];
  if (!task) {
    throw new Error(`No task mapped for cron: ${cron}`);
  }
  await dispatchWorkflow(task, env);
  return { ok: true, task, cron };
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

    await dispatchWorkflow(task, env);
    return Response.json({ ok: true, task });
  }

  return Response.json({ ok: false, error: "not found" }, { status: 404 });
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(handleCron(event.cron, env));
  },

  async fetch(request, env) {
    try {
      return await handleRequest(request, env);
    } catch (error) {
      return Response.json({ ok: false, error: String(error.message || error) }, { status: 500 });
    }
  },
};
