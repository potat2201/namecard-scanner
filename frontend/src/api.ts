export interface Contact {
  id: number;
  name: string | null;
  company: string | null;
  title: string | null;
  phone: string | null;
  email: string | null;
  website: string | null;
  address: string | null;
  raw_text: string | null;
  image_path: string | null;
  created_at: string;
}

export interface ScanResult {
  contact: Contact;
  raw_text: string;
  extraction_method: string;
  message: string;
  sync_warning?: string | null;
}

type ScanStreamEvent =
  | { type: "progress"; stage: string; message: string }
  | { type: "complete"; result: ScanResult }
  | { type: "error"; detail: string; status?: number };

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = (body as { detail?: string }).detail ?? res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return res.json() as Promise<T>;
}

export async function fetchContacts(q?: string): Promise<Contact[]> {
  const params = q ? `?q=${encodeURIComponent(q)}` : "";
  const res = await fetch(`/api/contacts${params}`);
  return handleResponse<Contact[]>(res);
}

export async function scanNamecard(
  file: File,
  onProgress?: (message: string) => void,
): Promise<ScanResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/scan/stream", { method: "POST", body: form });

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = (body as { detail?: string }).detail ?? res.statusText;
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }

  if (!res.body) {
    throw new Error("Scan failed: empty response");
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line) as ScanStreamEvent;
      if (event.type === "progress") {
        onProgress?.(event.message);
      } else if (event.type === "complete") {
        return event.result;
      } else if (event.type === "error") {
        throw new Error(event.detail);
      }
    }
  }

  throw new Error("Scan ended without a result");
}

export interface ClearDatabaseResult {
  deleted: number;
  files_removed: number;
  notion_archived: number;
  notion_errors: number;
}

export async function clearDatabase(): Promise<ClearDatabaseResult> {
  const res = await fetch("/api/contacts", { method: "DELETE" });
  return handleResponse<ClearDatabaseResult>(res);
}

export async function deleteContact(id: number): Promise<void> {
  const res = await fetch(`/api/contacts/${id}`, { method: "DELETE" });
  if (!res.ok) {
    throw new Error("Failed to delete contact");
  }
}

export async function updateContact(
  id: number,
  data: Partial<Omit<Contact, "id" | "created_at" | "raw_text" | "image_path">>,
): Promise<Contact> {
  const res = await fetch(`/api/contacts/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return handleResponse<Contact>(res);
}
