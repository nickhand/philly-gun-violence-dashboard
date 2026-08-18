function getUrlOrigin(value: unknown): string | null {
  try {
    return new URL(String(value ?? "").trim()).origin;
  } catch {
    return null;
  }
}

const SAFE_DOWNLOAD_PATH =
  /^(?!\/)(?!.*\/\/)(?!.*(?:^|\/)\.{1,2}(?:\/|$))[A-Za-z0-9][A-Za-z0-9._/-]*$/;
const SHA256 = /^[a-f0-9]{64}$/;

export interface PublicDownloadManifestEntry {
  id?: string;
  kind?: "records" | "geography";
  label?: string;
  filename: string;
  path: string;
  mediaType: string;
  byteSize: number;
  sha256?: string;
  rowCount?: number;
  dataset?: string;
  joinField?: string;
}

export interface PublicDownloadManifest {
  schemaVersion: 1 | 2;
  version: string;
  publishedAt: string;
  downloads: PublicDownloadManifestEntry[];
}

function isNonemptyString(value: unknown): value is string {
  return typeof value === "string" && Boolean(value.trim());
}

function isNonnegativeInteger(value: unknown): value is number {
  return (
    typeof value === "number" && Number.isSafeInteger(value) && value >= 0
  );
}

export function isSafePublicDownloadPath(value: unknown): value is string {
  return typeof value === "string" && SAFE_DOWNLOAD_PATH.test(value);
}

function parseLegacyEntry(value: unknown): PublicDownloadManifestEntry | null {
  if (!value || typeof value !== "object") return null;
  const entry = value as Record<string, unknown>;
  if (
    !isNonemptyString(entry.filename) ||
    entry.filename.includes("/") ||
    !isSafePublicDownloadPath(entry.path) ||
    !isNonemptyString(entry.media_type) ||
    !isNonnegativeInteger(entry.byte_size)
  ) {
    return null;
  }
  return {
    filename: entry.filename,
    path: entry.path,
    mediaType: entry.media_type,
    byteSize: entry.byte_size,
  };
}

function parseV2Entry(
  value: unknown,
  releaseId: string,
): PublicDownloadManifestEntry | null {
  if (!value || typeof value !== "object") return null;
  const entry = value as Record<string, unknown>;
  const kind = entry.kind;
  const expectedPrefix = `releases/${releaseId}/`;
  if (
    !isNonemptyString(entry.id) ||
    !["records", "geography"].includes(String(kind)) ||
    !isNonemptyString(entry.label) ||
    !isNonemptyString(entry.filename) ||
    entry.filename.includes("/") ||
    !isSafePublicDownloadPath(entry.path) ||
    !entry.path.startsWith(expectedPrefix) ||
    !isNonemptyString(entry.media_type) ||
    !isNonnegativeInteger(entry.byte_size) ||
    !isNonemptyString(entry.sha256) ||
    !SHA256.test(entry.sha256) ||
    !isNonnegativeInteger(entry.row_count)
  ) {
    return null;
  }

  if (
    kind === "geography" &&
    (!isNonemptyString(entry.dataset) || !isNonemptyString(entry.join_field))
  ) {
    return null;
  }
  if (kind === "records" && ("dataset" in entry || "join_field" in entry)) {
    return null;
  }

  return {
    id: entry.id,
    kind: kind as "records" | "geography",
    label: entry.label,
    filename: entry.filename,
    path: entry.path,
    mediaType: entry.media_type,
    byteSize: entry.byte_size,
    sha256: entry.sha256,
    rowCount: entry.row_count,
    ...(kind === "geography"
      ? { dataset: String(entry.dataset), joinField: String(entry.join_field) }
      : {}),
  };
}

export function parsePublicDownloadManifest(
  value: unknown,
): PublicDownloadManifest | null {
  if (!value || typeof value !== "object") return null;
  const manifest = value as Record<string, unknown>;
  if (!Array.isArray(manifest.downloads) || !isNonemptyString(manifest.version)) {
    return null;
  }

  if (manifest.schema_version === 1) {
    const downloads = manifest.downloads.map(parseLegacyEntry);
    if (downloads.some((entry) => entry === null)) return null;
    return {
      schemaVersion: 1,
      version: manifest.version,
      publishedAt: isNonemptyString(manifest.published_at)
        ? manifest.published_at
        : "",
      downloads: downloads as PublicDownloadManifestEntry[],
    };
  }

  if (
    manifest.schema_version !== 2 ||
    !manifest.version.startsWith("sha256:")
  ) {
    return null;
  }
  const releaseId = manifest.version.slice("sha256:".length);
  if (!SHA256.test(releaseId) || !isNonemptyString(manifest.published_at)) {
    return null;
  }
  const downloads = manifest.downloads.map((entry) =>
    parseV2Entry(entry, releaseId),
  );
  if (downloads.some((entry) => entry === null)) return null;

  const parsed = downloads as PublicDownloadManifestEntry[];
  const ids = parsed.map((entry) => entry.id);
  const paths = parsed.map((entry) => entry.path);
  if (new Set(ids).size !== ids.length || new Set(paths).size !== paths.length) {
    return null;
  }
  return {
    schemaVersion: 2,
    version: manifest.version,
    publishedAt: manifest.published_at,
    downloads: parsed,
  };
}

export function getPublicDownloadUrl(
  base: unknown,
  internalApiBase: unknown,
  filename: string,
): string | null {
  const value = String(base ?? "").trim();
  if (!value || !isSafePublicDownloadPath(filename)) return null;

  try {
    const url = new URL(value);
    const internalPathSegment =
      /\/(?:shootings|stats\.json|meta|openapi(?:\.json)?|docs)(?:\/|$)/i;

    if (
      !["http:", "https:"].includes(url.protocol) ||
      url.username ||
      url.password ||
      url.origin === getUrlOrigin(internalApiBase) ||
      url.hostname === "philly-gun-violence-dashboard-api.fly.dev" ||
      internalPathSegment.test(url.pathname)
    ) {
      return null;
    }

    url.search = "";
    url.hash = "";
    url.pathname = `${url.pathname.replace(/\/+$/, "")}/`;
    return new URL(filename, url).href;
  } catch {
    return null;
  }
}
