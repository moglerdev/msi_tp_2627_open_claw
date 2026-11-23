import { useCallback, useEffect, useState } from 'react'
import { api, contentText, type AuditRecord, type AuditSummary, type Leak, type Message } from '@/api'
import { Highlight, Placeholders } from '@/components/highlight'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { cn } from '@/lib/utils'

function StatusBadge({ s }: { s: AuditSummary['status'] }) {
  const ok = s === 200
  return <Badge variant={ok ? 'secondary' : 'destructive'}>{String(s ?? '–')}</Badge>
}

function Counts({ counts }: { counts: Record<string, number> }) {
  const e = Object.entries(counts)
  if (!e.length) return <span className="text-muted-foreground">–</span>
  return <span className="text-xs">{e.map(([k, v]) => `${k} ${v}`).join(' · ')}</span>
}

export function AuditView() {
  const [days, setDays] = useState(1)
  const [q, setQ] = useState('')
  const [rows, setRows] = useState<AuditSummary[]>([])
  const [sel, setSel] = useState<string | null>(null)
  const [err, setErr] = useState('')
  const [auto, setAuto] = useState(false)

  const load = useCallback(async () => {
    try { setRows(await api.audit(days, q)); setErr('') } catch (e) { setErr(String(e)) }
  }, [days, q])

  useEffect(() => { load() }, [load])
  useEffect(() => {
    if (!auto) return
    const t = setInterval(load, 3000)
    return () => clearInterval(t)
  }, [auto, load])

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
      <Card className="min-w-0">
        <CardHeader>
          <CardTitle>Audit log</CardTitle>
          <CardDescription>What reached the upstream (pseudonymized). Newest first.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Input className="w-20" type="number" min={1} value={days} onChange={(e) => setDays(Number(e.target.value) || 1)} />
            <span className="text-sm text-muted-foreground">days</span>
            <Input className="w-48" placeholder="Full-text search…" value={q} onChange={(e) => setQ(e.target.value)} />
            <Button variant="outline" onClick={load}>Reload</Button>
            <Button variant={auto ? 'default' : 'outline'} onClick={() => setAuto(!auto)}>{auto ? 'Live on' : 'Live off'}</Button>
            <span className="text-sm text-muted-foreground">{rows.length} entries</span>
          </div>
          {err && <p className="text-sm text-destructive">{err}</p>}
          <div className="max-h-[70vh] overflow-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Time</TableHead><TableHead>Status</TableHead><TableHead>Model</TableHead>
                  <TableHead>Replaced</TableHead><TableHead className="text-right">s</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.id} onClick={() => setSel(r.id)}
                    className={cn('cursor-pointer align-top', sel === r.id && 'bg-muted')}>
                    <TableCell className="whitespace-nowrap tabular-nums">{r.ts?.slice(5).replace('T', ' ')}</TableCell>
                    <TableCell><StatusBadge s={r.status} /></TableCell>
                    <TableCell className="max-w-64">
                      <div className="truncate text-xs">{r.model_used ?? r.model_requested}</div>
                      {r.attempts.length > 0 && <Badge variant="outline" className="mt-1">Fallback ×{r.attempts.length}</Badge>}
                      <div className="truncate text-xs text-muted-foreground" title={r.last_user}>{r.last_user}</div>
                    </TableCell>
                    <TableCell><Counts counts={r.counts} /></TableCell>
                    <TableCell className="text-right tabular-nums text-xs">{r.latency_s ?? '–'}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
      <div className="min-w-0">{sel ? <AuditDetail id={sel} /> : (
        <Card><CardContent className="py-10 text-center text-muted-foreground">Select an entry on the left</CardContent></Card>
      )}</div>
    </div>
  )
}

function MessageBlock({ m, idx, leaks }: { m: Message; idx: number; leaks: Leak[] }) {
  const text = contentText(m.content)
  const mine = leaks.filter((l) => l.message === idx)
  const isBlobSystem = m.role === 'system' && text.length > 2000
  const [open, setOpen] = useState(!isBlobSystem)
  return (
    <div className="rounded-lg border p-3">
      <div className="mb-2 flex items-center gap-2">
        <Badge variant={m.role === 'user' ? 'default' : 'outline'}>{m.role}</Badge>
        <span className="text-xs text-muted-foreground">#{idx} · {text.length} characters</span>
        {mine.length > 0 && <Badge variant="destructive">{mine.length} suspected leaks</Badge>}
        {isBlobSystem && <Button size="sm" variant="ghost" onClick={() => setOpen(!open)}>{open ? 'collapse' : 'show'}</Button>}
      </div>
      {open && (mine.length ? <LeakText text={text} leaks={mine} /> : <Placeholders text={text} />)}
      {m.tool_calls?.map((tc, i) => (
        <pre key={i} className="mt-2 overflow-auto rounded bg-muted p-2 text-xs">{tc.function?.name}({tc.function?.arguments})</pre>
      ))}
    </div>
  )
}

function LeakText({ text, leaks }: { text: string; leaks: Leak[] }) {
  const spans = []
  for (const l of leaks) {
    let from = 0, i
    while ((i = text.indexOf(l.text, from)) >= 0) {
      spans.push({ start: i, end: i + l.text.length, label: l.label, title: `Leak? ${l.label} ${l.score}`,
        className: 'bg-red-200 text-red-950 ring-red-500 dark:bg-red-900 dark:text-red-50' })
      from = i + l.text.length
    }
  }
  return <Highlight text={text} spans={spans} />
}

function AuditDetail({ id }: { id: string }) {
  const [rec, setRec] = useState<AuditRecord | null>(null)
  const [leaks, setLeaks] = useState<Leak[] | null>(null)
  const [thr, setThr] = useState(0.3)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  useEffect(() => {
    setRec(null); setLeaks(null); setErr('')
    api.auditItem(id).then(setRec).catch((e) => setErr(String(e)))
  }, [id])

  async function check() {
    setBusy(true)
    try { setLeaks(await api.leaks(id, thr)) } catch (e) { setErr(String(e)) } finally { setBusy(false) }
  }

  if (err) return <p className="text-destructive">{err}</p>
  if (!rec) return <p className="text-muted-foreground">Loading…</p>
  const msgs = rec.sent_messages ?? []
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-2">
          {rec.id} <StatusBadge s={rec.status} />
          {rec.stream && <Badge variant="outline">stream</Badge>}
        </CardTitle>
        <CardDescription className="space-y-1">
          <div>{rec.ts} · from {rec.client} · detection {rec.detect_s}s · Upstream {rec.latency_s}s</div>
          <div>requested <code>{rec.model_requested}</code> → used <code>{rec.model_used ?? '–'}</code></div>
          {rec.attempts?.length > 0 && <div>Failed attempts: {rec.attempts.join(' · ')}</div>}
          {rec.usage && <div>Usage: {Object.entries(rec.usage).filter(([, v]) => typeof v === 'number').map(([k, v]) => `${k} ${v}`).join(' · ')}</div>}
          <div>Replaced: <Counts counts={rec.counts ?? {}} /></div>
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-muted/50 p-2">
          <Button onClick={check} disabled={busy}>{busy ? 'Checking…' : 'Leak check'}</Button>
          <span className="text-sm text-muted-foreground">GLiNER threshold</span>
          <Input className="w-20" type="number" step="0.05" value={thr} onChange={(e) => setThr(Number(e.target.value))} />
          {leaks && <span className={cn('text-sm', leaks.length ? 'text-destructive' : 'text-muted-foreground')}>
            {leaks.length ? `${leaks.length} suspected values in plain text` : 'nothing found'}</span>}
        </div>
        {leaks && leaks.length > 0 && (
          <Table>
            <TableHeader><TableRow><TableHead>Value</TableHead><TableHead>Label</TableHead><TableHead>Score</TableHead><TableHead>Where</TableHead></TableRow></TableHeader>
            <TableBody>{leaks.map((l, i) => (
              <TableRow key={i}><TableCell className="font-mono">{l.text}</TableCell><TableCell>{l.label}</TableCell>
                <TableCell className="tabular-nums">{l.score}</TableCell><TableCell>{l.message >= 0 ? `#${l.message}` : ''} {l.source}</TableCell></TableRow>
            ))}</TableBody>
          </Table>
        )}
        <h3 className="font-medium">Sent ({msgs.length} messages)</h3>
        <div className="space-y-2">{msgs.map((m, i) => <MessageBlock key={i} m={m} idx={i} leaks={leaks ?? []} />)}</div>
        <h3 className="font-medium">Received</h3>
        {(rec.received ?? []).map((r, i) => (
          <div key={i} className="space-y-2 rounded-lg border p-3">
            {typeof r.reasoning === 'string' && r.reasoning && (
              <details><summary className="cursor-pointer text-xs text-muted-foreground">Reasoning</summary>
                <Placeholders text={r.reasoning} /></details>)}
            <MessageBlock m={{ role: 'assistant', content: r.content }} idx={-1} leaks={leaks ?? []} />
            {r.tool_calls != null && Object.keys(r.tool_calls as object).length > 0 &&
              <pre className="overflow-auto rounded bg-muted p-2 text-xs">{JSON.stringify(r.tool_calls, null, 2)}</pre>}
          </div>
        ))}
        {rec.sent_tools != null && (
          <details><summary className="cursor-pointer text-sm">Tool definitions ({Array.isArray(rec.sent_tools) ? rec.sent_tools.length : '?'})</summary>
            <pre className="max-h-96 overflow-auto rounded bg-muted p-2 text-xs">{JSON.stringify(rec.sent_tools, null, 2)}</pre></details>
        )}
      </CardContent>
    </Card>
  )
}
