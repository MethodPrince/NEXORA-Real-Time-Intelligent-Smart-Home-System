import type { Device } from "./types";

export type VoiceDeviceKind = "light" | "fan" | "curtain";
export type VoiceAction = "on" | "off" | "open" | "close";

export interface VoiceCommand {
  action: VoiceAction;
  kind: VoiceDeviceKind;
  target: string | null;
  all: boolean;
}

const fillerWords = new Set([
  "a",
  "all",
  "and",
  "can",
  "could",
  "every",
  "for",
  "hey",
  "hello",
  "hi",
  "in",
  "me",
  "method",
  "nexora",
  "my",
  "nora",
  "nona",
  "off",
  "on",
  "please",
  "the",
  "to",
  "turn",
  "switch",
  "would",
  "you",
]);

export function isAssistantGreeting(text: string): boolean {
  return /^(?:hey|hello|hi)\s+(?:method|nona|nora|nexora)[.,!?]*$/i.test(text.trim());
}

export function extractAssistantWakeCommand(text: string): string | null {
  const match = text.match(/\b(?:hey|hello|hi)\s+(?:method|nona|nora|nexora)\b[\s,.:;!?-]*/i);
  return match ? text.slice((match.index ?? 0) + match[0].length).trim() : null;
}

export function parseVoiceCommand(text: string): VoiceCommand | null {
  const normalized = text.toLowerCase().replace(/[^\p{L}\p{N}\s]/gu, " ").trim();
  const actionMatch = normalized.match(
    /\b(?:turn|switch|power)\s+(on|off)\b|\b(open|close)\b/,
  );
  const action = actionMatch?.[1] ?? actionMatch?.[2];
  if (action !== "on" && action !== "off" && action !== "open" && action !== "close") {
    return null;
  }

  const kindMatch = normalized.match(/\b(lights?|lamps?|fans?|curtains?)\b/);
  if (!kindMatch) return null;
  const token = kindMatch[1];
  const kind: VoiceDeviceKind = token.startsWith("light") || token.startsWith("lamp")
    ? "light"
    : token.startsWith("fan")
      ? "fan"
      : "curtain";
  if ((action === "open" || action === "close") !== (kind === "curtain")) return null;

  const targetTokens = normalized
    .replace(/\b(?:turn|switch|power)\s+(?:on|off)\b|\b(?:open|close)\b/g, " ")
    .replace(/\b(?:lights?|lamps?|fans?|curtains?)\b/g, " ")
    .split(/\s+/)
    .filter((word) => word && !fillerWords.has(word));
  return {
    action,
    kind,
    target: targetTokens.length ? targetTokens.join(" ") : null,
    all: /\b(?:all|every)\b/.test(normalized),
  };
}

export function voiceDeviceKind(deviceType: string): VoiceDeviceKind | null {
  const normalized = deviceType.toLowerCase();
  if (normalized.includes("light") || normalized.includes("lamp")) return "light";
  if (normalized.includes("fan")) return "fan";
  if (normalized.includes("curtain")) return "curtain";
  return null;
}

export function matchVoiceTargets<T extends Pick<Device, "device_type" | "name" | "room">>(
  devices: T[],
  command: VoiceCommand,
): T[] {
  const candidates = devices.filter(
    (device) => voiceDeviceKind(device.device_type) === command.kind,
  );
  if (command.all || !command.target) return candidates;

  const requestedWords = command.target.split(/\s+/);
  return candidates.filter((device) => {
    const label = `${device.name} ${device.room ?? ""}`.toLowerCase();
    return requestedWords.every((word) => label.includes(word));
  });
}
