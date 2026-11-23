export interface ErpMatchMemoryEntry {
  material_id: string
  name: string
  spec?: string | null
  unit?: string | null
  managed_class?: string | null
  saved_at: string
}

const MEMORY_KEY = 'fuxing:hw-erp-match-memory:v1'
const MAX_ENTRIES = 2000

export function erpMatchKey(name?: string | null, spec?: string | null): string {
  return `${(name ?? '').trim()}|${(spec ?? '').trim()}`
}

export function loadErpMatchMemory(): Record<string, ErpMatchMemoryEntry> {
  if (typeof window === 'undefined') return {}
  try {
    const raw = window.localStorage.getItem(MEMORY_KEY)
    return raw ? (JSON.parse(raw) as Record<string, ErpMatchMemoryEntry>) : {}
  } catch {
    return {}
  }
}

export function saveErpMatch(entry: {
  name?: string | null
  spec?: string | null
  material_id: string
  material_name: string
  material_spec?: string | null
  material_unit?: string | null
  material_class?: string | null
}): void {
  if (typeof window === 'undefined' || !entry.name?.trim()) return
  try {
    const memory = loadErpMatchMemory()
    memory[erpMatchKey(entry.name, entry.spec)] = {
      material_id: entry.material_id,
      name: entry.material_name,
      spec: entry.material_spec ?? null,
      unit: entry.material_unit ?? null,
      managed_class: entry.material_class ?? null,
      saved_at: new Date().toISOString(),
    }
    const keys = Object.keys(memory)
    if (keys.length > MAX_ENTRIES) {
      keys
        .sort((a, b) => (memory[a].saved_at < memory[b].saved_at ? -1 : 1))
        .slice(0, Math.floor(MAX_ENTRIES / 2))
        .forEach((k) => delete memory[k])
    }
    window.localStorage.setItem(MEMORY_KEY, JSON.stringify(memory))
  } catch {
  }
}
