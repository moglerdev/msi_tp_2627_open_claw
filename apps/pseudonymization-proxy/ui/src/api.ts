export type Candidate = {
  start: number
  end: number
  label: string
  norm_label: string
  score: number
  source: 'regex' | 'gliner'
  text: string
  status: 'kept' | 'skip_label' | 'below_threshold' | 'overlap' | 'too_short'
  final_start?: number
  final_end?: number
  placeholder?: string
}

export type DetectResult = {
  threshold: number
  gliner_ms: number
  candidates: Candidate[]
  segments: { start: number; end: number; placeholder: string; label: string }[]
  pseudonymized: string
  mapping: Record<string, string>
}

export type AuditSummary = {
  id: string
  ts: string
  client: string
  model_requested: string | null
  model_used: string | null
  status: number | string | null
  stream: boolean
  counts: Record<string, number>
  attempts: string[]
  detect_s: number | null
  latency_s: number | null
  n_messages: number
  usage?: Record<string, number> | null
  last_user: string
  answer: string
  has_tool_calls: boolean
}

export type Message = {
  role: string
  content?: unknown
  tool_calls?: { function?: { name?: string; arguments?: string } }[]
  tool_call_id?: string
  name?: string
}

export type AuditRecord = AuditSummary & {
  sent_messages?: Message[]
  sent_tools?: unknown
  received?: Record<string, unknown>[]
}

export type Leak = {
  message: number
  source: string
  label: string
  score: number
  text: string
  context: string
}

export type Config = {
  port: number
  upstream: string
  pii_url: string
  roles: string[]
  threshold: number
  fail_open: boolean
  fallback_models: string[]
  retry_status: number[]
  skip_labels: string[]
  regex_labels: string[]
  label_aliases: Record<string, string>
  audit: { on: boolean; dir: string; days: number; files: string[] }
  default_headers: string[]
  placeholder_note: string
  span_cache: number
  uptime_s: number
  stats: Record<string, number>
  pii: { ok: boolean; ms: number; body?: unknown; error?: string }
}

async function req<T>(path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, body === undefined ? undefined : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  const data = await r.json().catch(() => ({ error: `HTTP ${r.status}` }))
  if (!r.ok) throw new Error(data.error ?? `HTTP ${r.status}`)
  return data as T
}

export const api = {
  config: () => req<Config>('/debug/config'),
  detect: (text: string, threshold?: number) => req<DetectResult>('/debug/detect', { text, threshold }),
  preview: (messages: Message[]) =>
    req<{ body: { messages: Message[] }; mapping: Record<string, string>; counts: Record<string, number>; ms: number }>(
      '/debug/preview', { messages }),
  audit: (days: number, q: string, limit = 300) =>
    req<AuditSummary[]>(`/debug/audit?days=${days}&limit=${limit}&q=${encodeURIComponent(q)}`),
  auditItem: (id: string) => req<AuditRecord>(`/debug/audit/item?id=${encodeURIComponent(id)}`),
  leaks: (id: string, threshold: number) =>
    req<Leak[]>(`/debug/audit/leaks?id=${encodeURIComponent(id)}&threshold=${threshold}`),
}

/** Same color for the same label across all views. */
const PALETTE = [
  'bg-sky-100 text-sky-900 ring-sky-300 dark:bg-sky-950 dark:text-sky-100',
  'bg-amber-100 text-amber-900 ring-amber-300 dark:bg-amber-950 dark:text-amber-100',
  'bg-emerald-100 text-emerald-900 ring-emerald-300 dark:bg-emerald-950 dark:text-emerald-100',
  'bg-fuchsia-100 text-fuchsia-900 ring-fuchsia-300 dark:bg-fuchsia-950 dark:text-fuchsia-100',
  'bg-rose-100 text-rose-900 ring-rose-300 dark:bg-rose-950 dark:text-rose-100',
  'bg-violet-100 text-violet-900 ring-violet-300 dark:bg-violet-950 dark:text-violet-100',
  'bg-lime-100 text-lime-900 ring-lime-300 dark:bg-lime-950 dark:text-lime-100',
  'bg-orange-100 text-orange-900 ring-orange-300 dark:bg-orange-950 dark:text-orange-100',
]
export function labelColor(label: string) {
  let h = 0
  for (const c of label.replace(/_\d+$/, '')) h = (h * 31 + c.charCodeAt(0)) >>> 0
  return PALETTE[h % PALETTE.length]
}

export function contentText(c: unknown): string {
  if (typeof c === 'string') return c
  if (Array.isArray(c))
    return c.map((p) => (p && typeof p === 'object' && 'text' in p ? String(p.text) : `[${(p as { type?: string })?.type ?? '?'}]`)).join('\n')
  return c == null ? '' : JSON.stringify(c, null, 2)
}
