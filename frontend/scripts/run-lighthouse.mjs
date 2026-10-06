import { spawn } from "node:child_process";
import {
  access,
  mkdir,
  readFile,
  rm,
  writeFile,
} from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "@playwright/test";

import {
  evaluateLighthouseRuns,
  LIGHTHOUSE_POLICY,
} from "./lighthouse-policy.mjs";

const frontendRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outputDirectory = resolve(frontendRoot, "lighthouse-report");
const host = "127.0.0.1";
const appPort = 4174;
const apiPort = 4175;
const appOrigin = `http://${host}:${appPort}`;
const apiOrigin = `http://${host}:${apiPort}`;
const auditUrl = `${appOrigin}/philly-gun-violence-map/`;
const fixtureApiPath = resolve(
  frontendRoot,
  "tests/e2e/support/nuxtApiFixture.mjs",
);
const nitroServerPath = resolve(frontendRoot, ".output/server/index.mjs");
const lighthouseCliPath = resolve(
  frontendRoot,
  "node_modules/lighthouse/cli/index.js",
);

function delay(milliseconds) {
  return new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));
}

function runCommand(command, args, options = {}) {
  return new Promise((resolveCommand, rejectCommand) => {
    const child = spawn(command, args, {
      cwd: frontendRoot,
      stdio: "inherit",
      ...options,
    });
    child.once("error", rejectCommand);
    child.once("close", (code, signal) => {
      if (code === 0) {
        resolveCommand();
        return;
      }
      rejectCommand(
        new Error(
          `${command} exited with ${code ?? `signal ${signal ?? "unknown"}`}`,
        ),
      );
    });
  });
}

async function waitForServer(server, label, url) {
  const deadline = Date.now() + 20_000;
  let lastError;

  while (Date.now() < deadline) {
    if (server.exitCode !== null) {
      throw new Error(
        `${label} exited before becoming ready (${server.exitCode})`,
      );
    }

    try {
      const response = await fetch(url, {
        signal: AbortSignal.timeout(1_000),
      });
      if (response.ok) return;
      lastError = new Error(`${label} returned HTTP ${response.status}`);
    } catch (error) {
      lastError = error;
    }
    await delay(100);
  }

  throw new Error(`${label} did not become ready`, {
    cause: lastError,
  });
}

async function stopServer(server) {
  if (server.exitCode !== null) return;

  const closed = new Promise((resolveClose) => server.once("close", resolveClose));
  server.kill("SIGTERM");
  await Promise.race([closed, delay(5_000)]);
  if (server.exitCode === null) server.kill("SIGKILL");
}

async function main() {
  const chromePath = process.env.CHROME_PATH || chromium.executablePath();
  try {
    await access(nitroServerPath);
  } catch (error) {
    throw new Error("Run `npm run build` before auditing with Lighthouse.", {
      cause: error,
    });
  }
  await Promise.all([access(chromePath), access(lighthouseCliPath)]);

  await rm(outputDirectory, { force: true, recursive: true });
  await mkdir(outputDirectory, { recursive: true });

  const servers = [];
  try {
    const api = spawn(process.execPath, [fixtureApiPath], {
      cwd: frontendRoot,
      env: {
        ...process.env,
        NUXT_E2E_ALLOWED_ORIGIN: appOrigin,
        NUXT_E2E_API_PORT: String(apiPort),
      },
      stdio: "inherit",
    });
    servers.push(api);
    await waitForServer(api, "Lighthouse API fixture", `${apiOrigin}/health`);

    // Audit the production Nitro build against deterministic fixture data.
    // Analytics stays disabled so third-party scripts do not skew the scores.
    const app = spawn(process.execPath, [nitroServerPath], {
      cwd: frontendRoot,
      env: {
        ...process.env,
        HOST: host,
        PORT: String(appPort),
        NUXT_PUBLIC_API_BASE_URL: apiOrigin,
        NUXT_PUBLIC_DOWNLOADS_BASE_URL: apiOrigin,
        NUXT_PUBLIC_POSTHOG_KEY: "",
      },
      stdio: "inherit",
    });
    servers.push(app);
    await waitForServer(app, "Nuxt production server", auditUrl);
    const lhrs = [];

    for (let run = 1; run <= LIGHTHOUSE_POLICY.numberOfRuns; run += 1) {
      const outputPrefix = resolve(outputDirectory, `run-${run}`);
      console.log(`Running Lighthouse audit ${run}/${LIGHTHOUSE_POLICY.numberOfRuns}`);
      await runCommand(
        process.execPath,
        [
          lighthouseCliPath,
          auditUrl,
          "--preset=desktop",
          "--only-categories=performance,accessibility,best-practices,seo",
          "--output=json",
          "--output=html",
          `--output-path=${outputPrefix}`,
          "--chrome-flags=--headless=new --no-sandbox --disable-dev-shm-usage",
          "--quiet",
          "--no-enable-error-reporting",
        ],
        {
          env: {
            ...process.env,
            CHROME_PATH: chromePath,
          },
        },
      );

      const reportPath = `${outputPrefix}.report.json`;
      lhrs.push(JSON.parse(await readFile(reportPath, "utf8")));
    }

    const result = evaluateLighthouseRuns(lhrs);
    const summary = {
      generatedAt: new Date().toISOString(),
      lighthouseVersion: lhrs[0].lighthouseVersion,
      policy: LIGHTHOUSE_POLICY,
      ...result,
    };
    await writeFile(
      resolve(outputDirectory, "summary.json"),
      `${JSON.stringify(summary, null, 2)}\n`,
      "utf8",
    );

    console.table(result.medians);
    if (!result.passed) {
      throw new Error(
        `Lighthouse policy failed:\n- ${result.failures.join("\n- ")}`,
      );
    }
    console.log("Lighthouse policy passed");
  } finally {
    await Promise.all(servers.map(stopServer));
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
