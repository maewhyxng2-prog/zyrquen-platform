import { spawn } from "node:child_process";
import { cp, mkdir } from "node:fs/promises";

const standaloneDirectory = ".next/standalone";
await mkdir(`${standaloneDirectory}/.next`, { recursive: true });
await cp(".next/static", `${standaloneDirectory}/.next/static`, {
  recursive: true,
  force: true,
});

const server = spawn(process.execPath, [`${standaloneDirectory}/server.js`], {
  env: process.env,
  stdio: "inherit",
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => server.kill(signal));
}

server.on("exit", (code) => {
  process.exitCode = code ?? 1;
});
