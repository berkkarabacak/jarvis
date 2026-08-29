/**
 * Family talk policy for the Windows Jarvis shell.
 *
 * Berk sets the talk secret on the hosted server or in the private build
 * env (JARVIS_OPERATOR_OPENROUTER_KEY / OPENROUTER_API_KEY /
 * JARVIS_HOSTED_TALK_URL). Users never see a key field.
 *
 * Do not put a real key or a sk- / sk-or- placeholder in this file.
 */
const path = require("path");

const DEFAULT_HOSTED_TALK_URL = "https://berkkarabacak.com/jarvis";
const CANT_TALK = "Can't talk right now";

function shouldShowFirstRunKeyWindow(_opts) {
  // Packaged and unpackaged: never collect a key from Mom/grandpa.
  return false;
}

function parseEnvText(text) {
  const out = {};
  if (!text) return out;
  for (const raw of String(text).split(/\r?\n/)) {
    const line = raw.trim();
    if (!line || line.startsWith("#")) continue;
    const i = line.indexOf("=");
    if (i < 1) continue;
    let v = line.slice(i + 1).trim();
    if (
      (v.startsWith('"') && v.endsWith('"')) ||
      (v.startsWith("'") && v.endsWith("'"))
    ) {
      v = v.slice(1, -1);
    }
    out[line.slice(0, i).trim()] = v;
  }
  return out;
}

function blank(value) {
  return !String(value || "").trim();
}

function operatorEnvPaths(resourcesPath) {
  const root = resourcesPath || "";
  return [
    path.join(root, "operator.env"),
    path.join(root, "backend", "operator.env"),
  ];
}

function applyOperatorTalkEnv(env, opts) {
  const out = { ...(env || {}) };
  const options = opts || {};
  const processEnv = options.processEnv || {};
  const resourcesPath = options.resourcesPath || "";
  const isPackaged = options.isPackaged === true;
  const readFile =
    typeof options.readFile === "function"
      ? options.readFile
      : function () {
          return "";
        };

  if (blank(out.OPENROUTER_API_KEY) && !blank(processEnv.OPENROUTER_API_KEY)) {
    out.OPENROUTER_API_KEY = String(processEnv.OPENROUTER_API_KEY).trim();
  }
  if (
    blank(out.JARVIS_OPERATOR_OPENROUTER_KEY) &&
    !blank(processEnv.JARVIS_OPERATOR_OPENROUTER_KEY)
  ) {
    out.JARVIS_OPERATOR_OPENROUTER_KEY = String(
      processEnv.JARVIS_OPERATOR_OPENROUTER_KEY
    ).trim();
  }
  if (blank(out.JARVIS_HOSTED_TALK_URL) && !blank(processEnv.JARVIS_HOSTED_TALK_URL)) {
    out.JARVIS_HOSTED_TALK_URL = String(processEnv.JARVIS_HOSTED_TALK_URL).trim();
  }

  for (const file of operatorEnvPaths(resourcesPath)) {
    const parsed = parseEnvText(readFile(file));
    if (blank(out.JARVIS_OPERATOR_OPENROUTER_KEY) && parsed.JARVIS_OPERATOR_OPENROUTER_KEY) {
      out.JARVIS_OPERATOR_OPENROUTER_KEY = parsed.JARVIS_OPERATOR_OPENROUTER_KEY;
    }
    if (blank(out.OPENROUTER_API_KEY) && parsed.OPENROUTER_API_KEY) {
      out.OPENROUTER_API_KEY = parsed.OPENROUTER_API_KEY;
    }
    if (blank(out.JARVIS_HOSTED_TALK_URL) && parsed.JARVIS_HOSTED_TALK_URL) {
      out.JARVIS_HOSTED_TALK_URL = parsed.JARVIS_HOSTED_TALK_URL;
    }
  }

  const hasKey =
    !blank(out.OPENROUTER_API_KEY) || !blank(out.JARVIS_OPERATOR_OPENROUTER_KEY);
  if (!hasKey && blank(out.JARVIS_HOSTED_TALK_URL) && isPackaged) {
    out.JARVIS_HOSTED_TALK_URL = DEFAULT_HOSTED_TALK_URL;
  }
  return out;
}

module.exports = {
  DEFAULT_HOSTED_TALK_URL,
  CANT_TALK,
  shouldShowFirstRunKeyWindow,
  parseEnvText,
  operatorEnvPaths,
  applyOperatorTalkEnv,
};
