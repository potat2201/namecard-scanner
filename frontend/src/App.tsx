import { useCallback, useEffect, useRef, useState } from "react";
import {
  Contact,
  clearDatabase,
  deleteContact,
  fetchContacts,
  scanNamecard,
  updateContact,
} from "./api";
import "./App.css";

function formatDate(iso: string) {
  return new Date(iso).toLocaleString(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function formatDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes > 0) {
    return `${minutes} min ${seconds} sec`;
  }
  return `${seconds} sec`;
}

function cell(value: string | null) {
  return value?.trim() || "—";
}

function imageFiles(list: FileList | null | undefined): File[] {
  if (!list) return [];
  return Array.from(list).filter((f) => f.type.startsWith("image/"));
}

function summarizeBatch(
  results: { ok: boolean; message: string; name: string }[],
): { success: string | null; error: string | null } {
  const ok = results.filter((r) => r.ok);
  const failed = results.filter((r) => !r.ok);
  if (results.length === 1) {
    if (ok.length === 1) return { success: ok[0].message, error: null };
    return { success: null, error: `${failed[0].name}: ${failed[0].message}` };
  }

  const created = ok.filter((r) => r.message === "Contact created").length;
  const updated = ok.filter((r) => r.message === "Contact updated").length;
  const exists = ok.filter((r) => r.message === "Contact Already Exists").length;
  const parts: string[] = [];
  if (created) parts.push(`${created} created`);
  if (updated) parts.push(`${updated} updated`);
  if (exists) parts.push(`${exists} already existed`);

  let success: string | null = null;
  if (ok.length) {
    success = `Processed ${ok.length} of ${results.length} name cards` +
      (parts.length ? ` (${parts.join(", ")})` : "");
  }

  let error: string | null = null;
  if (failed.length) {
    const detail = failed
      .slice(0, 3)
      .map((r) => r.name)
      .join(", ");
    const more = failed.length > 3 ? ` and ${failed.length - 3} more` : "";
    error = `${failed.length} failed: ${detail}${more}`;
  }

  return { success, error };
}

export default function App() {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [scanStatus, setScanStatus] = useState("Saving photo…");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [lastMethod, setLastMethod] = useState<string | null>(null);
  const [lastProcessDurationMs, setLastProcessDurationMs] = useState<
    number | null
  >(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<Partial<Contact>>({});
  const cameraInputRef = useRef<HTMLInputElement>(null);
  const galleryInputRef = useRef<HTMLInputElement>(null);

  function clearFileInputs() {
    if (cameraInputRef.current) cameraInputRef.current.value = "";
    if (galleryInputRef.current) galleryInputRef.current.value = "";
  }

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchContacts(search || undefined);
      setContacts(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load contacts");
    } finally {
      setLoading(false);
    }
  }, [search]);

  useEffect(() => {
    const timer = setTimeout(load, 300);
    return () => clearTimeout(timer);
  }, [load]);

  async function handleScanFiles(files: File[]) {
    const images = files.filter((f) => f.type.startsWith("image/"));
    if (images.length === 0) return;

    setScanning(true);
    setScanStatus(
      images.length > 1
        ? `Name card 1 of ${images.length}: Saving photo…`
        : "Saving photo…",
    );
    setError(null);
    setSuccess(null);
    setLastMethod(null);
    setLastProcessDurationMs(null);

    const startedAt = Date.now();
    const results: {
      ok: boolean;
      message: string;
      name: string;
    }[] = [];

    try {
      for (let i = 0; i < images.length; i++) {
        const file = images[i];
        const prefix =
          images.length > 1 ? `Name card ${i + 1} of ${images.length}: ` : "";

        try {
          const result = await scanNamecard(file, (msg) =>
            setScanStatus(`${prefix}${msg}`),
          );
          setLastMethod(result.extraction_method);
          results.push({
            ok: true,
            message: result.message,
            name: file.name,
          });
        } catch (e) {
          const msg = e instanceof Error ? e.message : "Scan failed";
          results.push({ ok: false, message: msg, name: file.name });
        }
      }

      const okResults = results.filter((r) => r.ok);
      if (okResults.length > 0) {
        setLastProcessDurationMs(Date.now() - startedAt);
      }

      const { success, error } = summarizeBatch(results);
      setSuccess(success);
      setError(error);
      await load();
    } finally {
      setScanning(false);
      clearFileInputs();
    }
  }

  function onCameraSelected(e: React.ChangeEvent<HTMLInputElement>) {
    const files = imageFiles(e.target.files);
    if (files.length) void handleScanFiles(files.slice(0, 1));
  }

  function onGallerySelected(e: React.ChangeEvent<HTMLInputElement>) {
    const files = imageFiles(e.target.files);
    if (files.length) void handleScanFiles(files);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    const files = imageFiles(e.dataTransfer.files);
    if (files.length) void handleScanFiles(files);
  }

  async function onClearDatabase() {
    const confirmed = confirm(
      "Delete ALL contacts from this app?\n\n" +
        "• Local database and saved card photos on this server will be removed.\n" +
        "• All rows in your Notion namecard database will be removed (the database stays for future use).\n" +
        "• Google Drive is NOT changed — you need to manually clean up Google Drive namecards.\n\n" +
        "This cannot be undone.",
    );
    if (!confirmed) return;

    setError(null);
    setSuccess(null);
    try {
      const result = await clearDatabase();
      setContacts([]);
      setEditingId(null);
      setLastProcessDurationMs(null);
      setLastMethod(null);
      const parts = [
        `Cleared ${result.deleted} local contact${result.deleted === 1 ? "" : "s"}.`,
      ];
      if (result.notion_archived > 0) {
        parts.push(
          `Removed ${result.notion_archived} Notion record${result.notion_archived === 1 ? "" : "s"} (database kept).`,
        );
      }
      if (result.notion_errors > 0) {
        parts.push(`${result.notion_errors} Notion row(s) could not be removed.`);
      }
      parts.push("Remember to manually clean up Google Drive namecards if needed.");
      setSuccess(parts.join(" "));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to clear database");
    }
  }

  async function onDelete(id: number) {
    if (!confirm("Delete this contact?")) return;
    try {
      await deleteContact(id);
      setContacts((prev) => prev.filter((c) => c.id !== id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Delete failed");
    }
  }

  function startEdit(c: Contact) {
    setEditingId(c.id);
    setEditDraft({
      name: c.name,
      company: c.company,
      title: c.title,
      phone: c.phone,
      email: c.email,
      website: c.website,
      address: c.address,
    });
  }

  async function saveEdit() {
    if (editingId == null) return;
    try {
      const updated = await updateContact(editingId, editDraft);
      setContacts((prev) =>
        prev.map((c) => (c.id === editingId ? updated : c)),
      );
      setEditingId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Update failed");
    }
  }

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>Namecard Scanner</h1>
          <p className="subtitle">
            Upload business cards — extract contacts into your database
          </p>
        </div>
      </header>

      <section
        className={`upload-zone ${scanning ? "upload-zone--busy" : ""}`}
        onDragOver={(e) => e.preventDefault()}
        onDrop={onDrop}
        aria-busy={scanning}
      >
        <input
          ref={cameraInputRef}
          type="file"
          accept="image/*"
          capture="environment"
          hidden
          disabled={scanning}
          onChange={onCameraSelected}
        />
        <input
          ref={galleryInputRef}
          type="file"
          accept="image/*"
          multiple
          hidden
          disabled={scanning}
          onChange={onGallerySelected}
        />
        {scanning ? (
          <div className="upload-processing" role="status" aria-live="polite">
            <div className="spinner" aria-hidden="true" />
            <p className="upload-title">{scanStatus}</p>
            <p className="upload-hint">
              Each photo is one contact — this can take a while for multiple
              cards; please keep this page open
            </p>
          </div>
        ) : (
          <>
            <div className="upload-icon">📇</div>
            <p className="upload-title">Scan a name card</p>
            <p className="upload-hint">
              JPEG, PNG, HEIC — upload multiple cards at once, or drop images
              here on desktop
            </p>
            <div className="upload-actions">
              <button
                type="button"
                className="btn btn--primary upload-btn"
                onClick={() => cameraInputRef.current?.click()}
              >
                Take photo
              </button>
              <button
                type="button"
                className="btn upload-btn"
                onClick={() => galleryInputRef.current?.click()}
              >
                Upload photos
              </button>
            </div>
            {(lastProcessDurationMs != null || lastMethod) && (
              <p className="upload-meta">
                {lastProcessDurationMs != null && (
                  <>Processed in {formatDuration(lastProcessDurationMs)}</>
                )}
                {lastProcessDurationMs != null && lastMethod && " · "}
                {lastMethod && <>OCR: {lastMethod}</>}
              </p>
            )}
          </>
        )}
      </section>

      {success && (
        <div
          className={`banner ${
            success.includes("already existed")
              ? "banner--info"
              : "banner--success"
          }`}
          role="status"
        >
          <p className="banner-message">{success}</p>
          {lastProcessDurationMs != null && (
            <p className="banner-meta">
              Completed in {formatDuration(lastProcessDurationMs)}
            </p>
          )}
        </div>
      )}

      {error && (
        <div className="banner banner--error" role="alert">
          {error}
        </div>
      )}

      <section className="toolbar">
        <input
          type="search"
          className="search"
          placeholder="Search name, company, email, phone…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          disabled={scanning}
        />
        <span className="count">
          {loading ? "Loading…" : `${contacts.length} contact${contacts.length === 1 ? "" : "s"}`}
        </span>
        <button
          type="button"
          className="btn btn--danger toolbar-clear"
          onClick={() => void onClearDatabase()}
          disabled={scanning || loading || contacts.length === 0}
        >
          Clear database
        </button>
      </section>

      <section className="table-wrap">
        {contacts.length === 0 && !loading ? (
          <p className="empty">No contacts yet. Scan your first name card above.</p>
        ) : (
          <table className="contacts-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Company</th>
                <th>Title</th>
                <th>Phone</th>
                <th>Email</th>
                <th>Website</th>
                <th>Added</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {contacts.map((c) =>
                editingId === c.id ? (
                  <tr key={c.id} className="edit-row">
                    <td>
                      <input
                        value={editDraft.name ?? ""}
                        onChange={(e) =>
                          setEditDraft((d) => ({ ...d, name: e.target.value }))
                        }
                      />
                    </td>
                    <td>
                      <input
                        value={editDraft.company ?? ""}
                        onChange={(e) =>
                          setEditDraft((d) => ({
                            ...d,
                            company: e.target.value,
                          }))
                        }
                      />
                    </td>
                    <td>
                      <input
                        value={editDraft.title ?? ""}
                        onChange={(e) =>
                          setEditDraft((d) => ({ ...d, title: e.target.value }))
                        }
                      />
                    </td>
                    <td>
                      <input
                        value={editDraft.phone ?? ""}
                        onChange={(e) =>
                          setEditDraft((d) => ({ ...d, phone: e.target.value }))
                        }
                      />
                    </td>
                    <td>
                      <input
                        value={editDraft.email ?? ""}
                        onChange={(e) =>
                          setEditDraft((d) => ({ ...d, email: e.target.value }))
                        }
                      />
                    </td>
                    <td>
                      <input
                        value={editDraft.website ?? ""}
                        onChange={(e) =>
                          setEditDraft((d) => ({
                            ...d,
                            website: e.target.value,
                          }))
                        }
                      />
                    </td>
                    <td colSpan={2} className="edit-actions">
                      <button type="button" className="btn btn--primary" onClick={saveEdit}>
                        Save
                      </button>
                      <button
                        type="button"
                        className="btn"
                        onClick={() => setEditingId(null)}
                      >
                        Cancel
                      </button>
                    </td>
                  </tr>
                ) : (
                  <tr key={c.id}>
                    <td>{cell(c.name)}</td>
                    <td>{cell(c.company)}</td>
                    <td>{cell(c.title)}</td>
                    <td>{cell(c.phone)}</td>
                    <td>
                      {c.email ? (
                        <a href={`mailto:${c.email}`}>{c.email}</a>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td>
                      {c.website ? (
                        <a href={c.website} target="_blank" rel="noreferrer">
                          {c.website.replace(/^https?:\/\//, "")}
                        </a>
                      ) : (
                        "—"
                      )}
                    </td>
                    <td className="muted">{formatDate(c.created_at)}</td>
                    <td className="actions">
                      <button
                        type="button"
                        className="btn btn--ghost"
                        onClick={() => startEdit(c)}
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        className="btn btn--danger"
                        onClick={() => onDelete(c.id)}
                      >
                        Delete
                      </button>
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}
