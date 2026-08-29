/**
 * Node assertions for desktop/talk-policy.js (packaged talk, no key window).
 * Run: node desktop/talk-policy.test.js
 */
const assert = require("assert");
const path = require("path");
const {
  DEFAULT_HOSTED_TALK_URL,
  CANT_TALK,
  shouldShowFirstRunKeyWindow,
  applyOperatorTalkEnv,
  operatorEnvPaths,
} = require("./talk-policy");

assert.strictEqual(shouldShowFirstRunKeyWindow({ isPackaged: true, needsKey: true }), false);
assert.strictEqual(shouldShowFirstRunKeyWindow({ isPackaged: false, needsKey: true }), false);
assert.strictEqual(shouldShowFirstRunKeyWindow({}), false);

assert.strictEqual(DEFAULT_HOSTED_TALK_URL, "https://aicontrolroom.nl/jarvis");
assert.strictEqual(CANT_TALK, "Can't talk right now");

const hosted = applyOperatorTalkEnv(
  { OPENROUTER_API_KEY: "" },
  { isPackaged: true, processEnv: {}, resourcesPath: "/res", readFile: () => "" }
);
assert.strictEqual(hosted.JARVIS_HOSTED_TALK_URL, DEFAULT_HOSTED_TALK_URL);
assert.ok(!hosted.OPENROUTER_API_KEY);

const unpackaged = applyOperatorTalkEnv(
  { OPENROUTER_API_KEY: "" },
  { isPackaged: false, processEnv: {}, resourcesPath: "/res", readFile: () => "" }
);
assert.ok(!unpackaged.JARVIS_HOSTED_TALK_URL, "dev clone does not invent a hosted URL");

const fromProcess = applyOperatorTalkEnv(
  { OPENROUTER_API_KEY: "" },
  {
    isPackaged: true,
    processEnv: { JARVIS_OPERATOR_OPENROUTER_KEY: "operator-from-packager" },
    resourcesPath: "/res",
    readFile: () => "",
  }
);
assert.strictEqual(fromProcess.JARVIS_OPERATOR_OPENROUTER_KEY, "operator-from-packager");
assert.ok(!fromProcess.JARVIS_HOSTED_TALK_URL, "operator key wins; no need to default hosted");

const files = {};
files[path.join("/res", "backend", "operator.env")] =
  "JARVIS_OPERATOR_OPENROUTER_KEY=operator-from-extra-resources\n";
const fromFile = applyOperatorTalkEnv(
  { OPENROUTER_API_KEY: "" },
  {
    isPackaged: true,
    processEnv: {},
    resourcesPath: "/res",
    readFile: (p) => files[p] || "",
  }
);
assert.strictEqual(fromFile.JARVIS_OPERATOR_OPENROUTER_KEY, "operator-from-extra-resources");

const keepUser = applyOperatorTalkEnv(
  { OPENROUTER_API_KEY: "user-local-env-value" },
  {
    isPackaged: true,
    processEnv: { JARVIS_OPERATOR_OPENROUTER_KEY: "operator-should-not-clobber-user" },
    resourcesPath: "/res",
    readFile: () => "JARVIS_OPERATOR_OPENROUTER_KEY=file-should-not-clobber-user\n",
  }
);
assert.strictEqual(keepUser.OPENROUTER_API_KEY, "user-local-env-value");

const paths = operatorEnvPaths("/res");
assert.ok(paths.some((p) => p.endsWith(path.join("backend", "operator.env"))));

console.log("talk-policy helpers ok");
