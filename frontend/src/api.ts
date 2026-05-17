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
}

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

export async function scanNamecard(file: File): Promise<ScanResult> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/scan", { method: "POST", body: form });
  return handleResponse<ScanResult>(res);
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
