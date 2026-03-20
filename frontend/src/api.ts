import type {
  Encounter,
  EncounterWithMessages,
  Message,
  Room,
} from "./types";

const API_BASE_URL =
  (import.meta as any).env?.VITE_API_BASE_URL ?? "http://127.0.0.1:8001";

async function requestJson<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...(options?.headers ?? {}) },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`);
  }
  return (await res.json()) as T;
}

export async function createEncounter(): Promise<
  Encounter & { can_interact: boolean; messages: Message[] }
> {
  return requestJson("/encounters", { method: "POST" });
}

export async function getMessages(encounterId: string): Promise<
  EncounterWithMessages
> {
  return requestJson(`/encounters/${encounterId}/messages`, { method: "GET" });
}

export async function moveEncounter(
  encounterId: string,
  room: Room
): Promise<{ encounter: Encounter; can_interact: boolean; suggested_next_action?: string | null }> {
  return requestJson(`/encounters/${encounterId}/move`, {
    method: "POST",
    body: JSON.stringify({ room }),
  });
}

export async function sendPatientMessage(
  encounterId: string,
  content: string
): Promise<EncounterWithMessages> {
  return requestJson(`/encounters/${encounterId}/messages`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export async function orderTest(
  encounterId: string
): Promise<{ encounter: Encounter; messages: Message[]; error?: string }> {
  return requestJson(`/encounters/${encounterId}/order-test`, { method: "POST" });
}

export async function finishEncounter(
  encounterId: string
): Promise<{ encounter: Encounter; messages: Message[]; error?: string }> {
  return requestJson(`/encounters/${encounterId}/finish`, { method: "POST" });
}

export async function resetEncounter(
  encounterId: string
): Promise<Encounter & { can_interact: boolean; messages: Message[] }> {
  return requestJson(`/encounters/${encounterId}/reset`, { method: "POST" });
}

