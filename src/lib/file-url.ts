/**
 * Convert a file path (object_key or local path) into a proxy URL.
 *
 * With MinIO, all file access goes through:
 *   GET /api/v1/safety/files/{encoded_path}
 *
 * Usage:
 *   import { fileProxyUrl } from '@/lib/file-url'
 *   <Image src={fileProxyUrl(record.defect_photos)} />
 */
export function fileProxyUrl(path: string | null | undefined): string {
  if (!path) return ''
  if (path.startsWith('http')) return path

  const base =
    process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1'

  // Encode each path segment separately to preserve / as directory separator.
  // encodeURIComponent encodes / as %2F, but the backend's MinIO object keys
  // and local paths use literal / — the mismatch causes 404.
  const encoded = path
    .split('/')
    .map((seg) => encodeURIComponent(seg))
    .join('/')
  return `${base}/safety/files/${encoded}`
}
