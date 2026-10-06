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
const basePath = "/philly-gun-violence-map/";
const appOrigin = `http://${host}:${appPort}`;
const apiOrigin = `http://${host}:${apiPort}`;
const auditUrl = `${appOrigin}${basePath}`;
// Audit the built Nuxt server (`npm run build:lighthouse`) against the same
// deterministic API fixture the Nuxt browser tests use.
const apiFixturePath = resolve(
  frontendRoot,
  "tests/e2e/support/nuxtApiFixture.mjs",
);
const nuxtServerPath = resolve(frontendRoot, ".output/server/index.mjs");
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

async function waitForServer(server, url, label) {
  const deadline = Date.now() + 30_000;
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
  await Promise.all([
    access(chromePath),
    access(lighthouseCliPath),
    access(nuxtServerPath),
  ]);

  await rm(outputDirectory, { force: true, recursive: true });
  await mkdir(outputDirectory, { recursive: true });

  const api = spawn(process.execPath, [apiFixturePath], {
    cwd: frontendRoot,
    stdio: "inherit",
    env: {
      ...process.env,
      NUXT_E2E_ALLOWED_ORIGIN: appOrigin,
      NUXT_E2E_API_PORT: String(apiPort),
    },
  });
  const app = spawn(process.execPath, [nuxtServerPath], {
    cwd: frontendRoot,
    stdio: "inherit",
    env: {
      ...process.env,
      HOST: host,
      NITRO_HOST: host,
      NITRO_PORT: String(appPort),
      NUXT_APP_BASE_URL: basePath,
      NUXT_PUBLIC_API_BASE_URL: apiOrigin,
      NUXT_PUBLIC_DOWNLOADS_BASE_URL:
        "https://data.example.test/philly-shooting-records",
      NUXT_PUBLIC_POSTHOG_KEY: "",
    },
  });

  try {
    await waitForServer(api, `${apiOrigin}/health`, "Lighthouse API fixture");
    await waitForServer(app, auditUrl, "Nuxt server");
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
    await Promise.all([stopServer(app), stopServer(api)]);
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
