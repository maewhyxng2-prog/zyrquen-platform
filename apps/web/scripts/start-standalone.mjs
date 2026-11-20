import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { cp, mkdir } from "node:fs/promises";
import path from "node:path";

const monorepoAppDir = ".next/standalone/apps/web";
const standaloneDirectory = existsSync(path.join(monorepoAppDir, "server.js"))
  ? monorepoAppDir
  : ".next/standalone";

await mkdir(`${standaloneDirectory}/.next`, { recursive: true });
await cp(".next/static", `${standaloneDirectory}/.next/static`, {
  recursive: true,
  force: true,
});

const server = spawn(process.execPath, [`${standaloneDirectory}/server.js`], {
  env: {
    HOSTNAME: "0.0.0.0",
    PORT: "3000",
    ...process.env,
  },
  stdio: "inherit",
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.kill(signal));
}

server.on("exit", (code) => {
  process.exitCode = code ?? 1;
});
