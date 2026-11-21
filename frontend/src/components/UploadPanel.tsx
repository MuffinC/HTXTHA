// Upload panel: drag-and-drop or browse, profile choice, client-side checks,
// and per-file reasons for anything the server rejects.
import { useRef, useState, type DragEvent } from 'react';
import { ApiError, NetworkError, api } from '../api/client';
import type { ConfigResponse, JobCreatedResponse, Profile, ProfileInfo, RejectedFile } from '../api/types';
import { REJECTION_LABEL, formatBytes, plural } from '../lib/labels';
import { addFiles, applyCountLimit, type FileEntry } from '../lib/validateFiles';
import { Icon } from './Icon';

export interface UploadPanelProps {
  config: ConfigResponse | null;
  profiles: ProfileInfo[] | null;
  /** Why uploading is blocked right now (model not ready, backend down), or null. */
  blockedReason: string | null;
  onCreated: (response: JobCreatedResponse) => void;
}

export function UploadPanel({ config, profiles, blockedReason, onCreated }: UploadPanelProps) {
  const [entries, setEntries] = useState<FileEntry[]>([]);
  const [profile, setProfile] = useState<Profile>('general');
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [serverRejected, setServerRejected] = useState<RejectedFile[]>([]);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const valid = entries.filter((e) => e.problem === null);
  const selectedProfile = profiles?.find((p) => p.id === profile);

  const add = async (files: FileList | null) => {
    if (!files || !config) return;
    setError(null);
    setServerRejected([]);
    setEntries(await addFiles(entries, Array.from(files), config));
  };

  const remove = (id: string) => {
    if (!config) return;
    setEntries(applyCountLimit(entries.filter((e) => e.id !== id), config.max_files));
  };

  const onDrop = (event: DragEvent) => {
    event.preventDefault();
    setDragging(false);
    void add(event.dataTransfer.files);
  };

  const submit = async () => {
    setUploading(true);
    setError(null);
    setServerRejected([]);
    try {
      const response = await api.createJob(
        valid.map((e) => e.file),
        profile,
      );
      setEntries([]);
      onCreated(response);
    } catch (err) {
      if (err instanceof ApiError && err.code === 'NO_VALID_FILES') {
        setServerRejected((err.details.rejected as RejectedFile[] | undefined) ?? []);
        setError('None of the files could be accepted.');
      } else if (err instanceof ApiError) {
        setError(err.message);
      } else if (err instanceof NetworkError) {
        setError('The backend could not be reached. Your files are still listed; try again.');
      } else {
        setError('The upload failed unexpectedly.');
      }
    } finally {
      setUploading(false);
    }
  };

  const disabled = !config || uploading || valid.length === 0 || blockedReason !== null;

  return (
    <section className="panel upload" aria-labelledby="upload-title">
      <h2 id="upload-title" className="panel-title">
        New analysis
      </h2>

      <div
        className={`dropzone${dragging ? ' is-dragging' : ''}`}
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
      >
        <Icon name="upload" />
        <p>
          Drop PDF files here or{' '}
          <button type="button" className="link-button" onClick={() => inputRef.current?.click()}>
            browse
          </button>
        </p>
        <p className="muted small">
          {config
            ? `Up to ${config.max_files} files · ${config.max_file_mb} MB and ${config.max_pages} pages each`
            : 'Loading limits…'}
        </p>
        <input
          ref={inputRef}
          type="file"
          accept="application/pdf,.pdf"
          multiple
          hidden
          data-testid="file-input"
          onChange={(e) => {
            void add(e.target.files);
            e.target.value = '';
          }}
        />
      </div>

      <label className="field">
        <span className="field-label">Analysis profile</span>
        <select value={profile} onChange={(e) => setProfile(e.target.value as Profile)}>
          {(profiles ?? [{ id: 'general', name: 'General', description: '', available: true }]).map(
            (p) => (
              <option key={p.id} value={p.id} disabled={!p.available}>
                {p.name}
                {p.available ? '' : ' (coming later)'}
              </option>
            ),
          )}
        </select>
        {selectedProfile?.description && (
          <span className="field-hint">{selectedProfile.description}</span>
        )}
      </label>

      {entries.length > 0 && (
        <ul className="file-list" aria-label="Selected files">
          {entries.map((entry) => (
            <li key={entry.id} className={entry.problem ? 'is-invalid' : ''}>
              <Icon name={entry.problem ? 'cross' : 'file'} />
              <div className="file-meta">
                <span className="file-name">{entry.file.name}</span>
                <span className={entry.problem ? 'file-problem' : 'muted small'}>
                  {entry.problem ?? formatBytes(entry.file.size)}
                </span>
              </div>
              <button
                type="button"
                className="icon-button"
                onClick={() => remove(entry.id)}
                aria-label={`Remove ${entry.file.name}`}
              >
                <Icon name="close" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {serverRejected.length > 0 && (
        <ul className="file-list" aria-label="Files rejected by the server">
          {serverRejected.map((r, i) => (
            <li key={i} className="is-invalid">
              <Icon name="cross" />
              <div className="file-meta">
                <span className="file-name">{r.filename}</span>
                <span className="file-problem">
                  {REJECTION_LABEL[r.code] ?? r.code}: {r.message}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}

      {error && (
        <p className="form-error" role="alert">
          <Icon name="alert" /> {error}
        </p>
      )}

      <button type="button" className="button-primary" disabled={disabled} onClick={submit}>
        {uploading ? (
          <>
            <Icon name="spinner" className="spin" /> Uploading…
          </>
        ) : valid.length > 0 ? (
          `Analyse ${plural(valid.length, 'document')}`
        ) : (
          'Analyse'
        )}
      </button>
      {blockedReason && valid.length > 0 && <p className="muted small">{blockedReason}</p>}
    </section>
  );
}
