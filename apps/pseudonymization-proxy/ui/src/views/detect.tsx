import { useState } from 'react'
import { api, labelColor, type Candidate, type DetectResult } from '@/api'
import { Highlight, Placeholders } from '@/components/highlight'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Textarea } from '@/components/ui/textarea'

const SAMPLE =
  'Hi, this is Dr. Julia Hartmann from Konstanz. Please call Tobias Brenner at 0171 2345678 ' +
  'or write to t.brenner@example.org. IBAN DE89 3704 0044 0532 0130 00, Server 10.0.0.12.'

const STATUS: Record<Candidate['status'], { text: string; variant: 'default' | 'secondary' | 'outline' | 'destructive' }> = {
  kept: { text: 'replaced', variant: 'default' },
  below_threshold: { text: 'below threshold', variant: 'outline' },
  overlap: { text: 'overlap', variant: 'secondary' },
  skip_label: { text: 'label skipped', variant: 'secondary' },
  too_short: { text: 'too short', variant: 'outline' },
}

export function DetectView({ defaultThreshold }: { defaultThreshold?: number }) {
  const [text, setText] = useState(SAMPLE)
  const [thr, setThr] = useState<string>('')
  const [res, setRes] = useState<DetectResult | null>(null)
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  async function run() {
    setBusy(true); setErr('')
    try {
      setRes(await api.detect(text, thr === '' ? undefined : Number(thr)))
    } catch (e) { setErr(String(e)) } finally { setBusy(false) }
  }

  const kept = res?.candidates.filter((c) => c.status === 'kept') ?? []
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>Check text</CardTitle>
          <CardDescription>
            Regex + GLiNER as in the proxy, but without cache and with all rejected candidates.
            GLiNER is queried with min(threshold, 0.3) so near-misses become visible.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea rows={5} value={text} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) run() }} />
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={run} disabled={busy}>{busy ? 'Detecting…' : 'Detect (Ctrl+Enter)'}</Button>
            <span className="text-sm text-muted-foreground">Threshold</span>
            <Input className="w-24" type="number" step="0.05" min="0" max="1"
              placeholder={String(defaultThreshold ?? 0.5)} value={thr} onChange={(e) => setThr(e.target.value)} />
            {res && <span className="text-sm text-muted-foreground">GLiNER {res.gliner_ms} ms · {kept.length} replaced · {res.candidates.length} candidates</span>}
            {err && <span className="text-sm text-destructive">{err}</span>}
          </div>
        </CardContent>
      </Card>

      {res && <>
        <Card>
          <CardHeader><CardTitle>Original, highlighted</CardTitle></CardHeader>
          <CardContent>
            <Highlight text={text} spans={kept.map((c) => ({
              start: c.final_start!, end: c.final_end!, label: c.norm_label,
              title: `${c.placeholder} · ${c.label} · ${c.source} · ${c.score}`,
            }))} />
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>What the upstream sees</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <Placeholders text={res.pseudonymized} mapping={res.mapping} />
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(res.mapping).map(([k, v]) => (
                <span key={k} className={`rounded px-1.5 py-0.5 text-xs ring-1 ${labelColor(k)}`}>{k} = {v}</span>
              ))}
            </div>
          </CardContent>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader><CardTitle>All candidates</CardTitle></CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Text</TableHead><TableHead>Label</TableHead><TableHead>→</TableHead>
                  <TableHead>Source</TableHead><TableHead className="text-right">Score</TableHead>
                  <TableHead>Pos.</TableHead><TableHead>Decision</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {res.candidates.map((c, i) => (
                  <TableRow key={i} className={c.status === 'kept' ? '' : 'opacity-60'}>
                    <TableCell className="font-mono">{c.text}</TableCell>
                    <TableCell>{c.label}</TableCell>
                    <TableCell><span className={`rounded px-1 text-xs ring-1 ${labelColor(c.norm_label)}`}>{c.placeholder ?? c.norm_label}</span></TableCell>
                    <TableCell><Badge variant="outline">{c.source}</Badge></TableCell>
                    <TableCell className="text-right tabular-nums">{c.score.toFixed(2)}</TableCell>
                    <TableCell className="tabular-nums text-muted-foreground">{c.start}–{c.end}</TableCell>
                    <TableCell><Badge variant={STATUS[c.status].variant}>{STATUS[c.status].text}</Badge></TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </>}
    </div>
  )
}
