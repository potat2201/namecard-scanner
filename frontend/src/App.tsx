import { useCallback, useEffect, useRef, useState } from "react";
import {
  Contact,
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

function cell(value: string | null) {
  return value?.trim() || "—";
}

export default function App() {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [lastMethod, setLastMethod] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<Partial<Contact>>({});
  const fileRef = useRef<HTMLInputElement>(null);

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

  async function handleScan(file: File) {
    setScanning(true);
    setError(null);
    setSuccess(null);
    setLastMethod(null);
    try {
      const result = await scanNamecard(file);
      setLastMethod(result.extraction_method);
      setSuccess(result.message);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scan failed");
    } finally {
      setScanning(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function onFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) void handleScan(file);
  }

  function onDrop(e: React.DragEvent) {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file?.type.startsWith("image/")) void handleScan(file);
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
        onClick={() => fileRef.current?.click()}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => e.key === "Enter" && fileRef.current?.click()}
      >
        <input
          ref={fileRef}
          type="file"
          accept="image/*"
          capture="environment"
          hidden
          onChange={onFileChange}
        />
        <div className="upload-icon">📇</div>
        <p className="upload-title">
          {scanning ? "Scanning card…" : "Drop a name card or click to upload"}
        </p>
        <p className="upload-hint">JPEG, PNG, HEIC — phone camera works too</p>
        {lastMethod && (
          <p className="upload-meta">Last scan: {lastMethod}</p>
        )}
      </section>

      {success && (
        <div
          className={`banner ${
            success === "Contact Already Exists"
              ? "banner--info"
              : "banner--success"
          }`}
          role="status"
        >
          {success}
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
        />
        <span className="count">
          {loading ? "Loading…" : `${contacts.length} contact${contacts.length === 1 ? "" : "s"}`}
        </span>
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
