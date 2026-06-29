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

  return `${base}/safety/files/${encodeURIComponent(path)}`
}
