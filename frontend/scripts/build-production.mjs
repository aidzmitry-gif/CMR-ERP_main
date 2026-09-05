import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

import { productionEnvErrors } from "./production-env.mjs";

export { productionEnvErrors } from "./production-env.mjs";

export function main(env = process.env) {
  const errors = productionEnvErrors(env);
  if (errors.length) {
    console.error("Production frontend build refused:");
    for (const error of errors) console.error(`- ${error}`);
    return 1;
  }

  const nextBin = fileURLToPath(new URL("../node_modules/next/dist/bin/next", import.meta.url));
  const child = spawn(process.execPath, [nextBin, "build"], {
    cwd: fileURLToPath(new URL("..", import.meta.url)),
    env,
    stdio: "inherit",
  });
  child.on("exit", (code, signal) => {
    process.exitCode = code ?? (signal ? 1 : 0);
  });
  child.on("error", (error) => {
    console.error(`Unable to start Next production build: ${error.message}`);
    process.exitCode = 1;
  });
  return 0;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  process.exitCode = main();
}
