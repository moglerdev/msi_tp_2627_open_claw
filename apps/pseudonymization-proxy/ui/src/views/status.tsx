import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { Config } from '@/api'

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[12rem_1fr] gap-2 border-b py-1.5 text-sm last:border-0">
      <span className="text-muted-foreground">{k}</span><span className="min-w-0 break-words">{children}</span>
    </div>
  )
}

function fmtUptime(s: number) {
  const d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60)
  return `${d ? d + 'd ' : ''}${h}h ${m}m`
}

export function StatusView({ cfg }: { cfg: Config | null }) {
  if (!cfg) return <p className="text-muted-foreground">Loading…</p>
  const stats = ['requests', 'replaced_values', 'fallback_used', 'all_failed', 'refused_pii_down']
  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card className="lg:col-span-2">
        <CardHeader><CardTitle>Since start ({fmtUptime(cfg.uptime_s)})</CardTitle></CardHeader>
        <CardContent className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          {stats.map((s) => (
            <div key={s} className="rounded-lg border p-3">
              <div className="text-2xl font-semibold tabular-nums">{cfg.stats[s] ?? 0}</div>
              <div className="text-xs text-muted-foreground">{s}</div>
            </div>
          ))}
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Proxy</CardTitle></CardHeader>
        <CardContent>
          <Row k="Port">{cfg.port}</Row>
          <Row k="Upstream"><code>{cfg.upstream}</code></Row>
          <Row k="Roles">{cfg.roles.join(', ')}</Row>
          <Row k="Threshold">{cfg.threshold}</Row>
          <Row k="Fail open">{cfg.fail_open ? <Badge variant="destructive">yes</Badge> : 'no (fail closed)'}</Row>
          <Row k="Fallback chain"><ol className="list-decimal pl-5">{cfg.fallback_models.map((m) => <li key={m}><code>{m}</code></li>)}</ol></Row>
          <Row k="Retry on">{cfg.retry_status.join(', ')}</Row>
          <Row k="Added headers">{cfg.default_headers.join(', ') || '–'}</Row>
          <Row k="Span-Cache">{cfg.span_cache} entries</Row>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Detection &amp; audit</CardTitle></CardHeader>
        <CardContent>
          <Row k="PII service"><code>{cfg.pii_url}</code>{' '}
            <Badge variant={cfg.pii.ok ? 'secondary' : 'destructive'}>{cfg.pii.ok ? `ok, ${cfg.pii.ms} ms` : cfg.pii.error}</Badge></Row>
          <Row k="Regex-Labels">{cfg.regex_labels.join(', ')}</Row>
          <Row k="Skipped labels">{cfg.skip_labels.join(', ')}</Row>
          <Row k="Label aliases">{Object.entries(cfg.label_aliases).map(([a, b]) => `${a}→${b}`).join(', ')}</Row>
          <Row k="Audit">{cfg.audit.on ? `on, ${cfg.audit.days} days` : 'off'} · <code>{cfg.audit.dir}</code></Row>
          <Row k="Audit files">{cfg.audit.files.length ? `${cfg.audit.files[0]} … ${cfg.audit.files.at(-1)} (${cfg.audit.files.length})` : '–'}</Row>
          <Row k="Placeholder note"><span className="text-xs">{cfg.placeholder_note}</span></Row>
        </CardContent>
      </Card>
    </div>
  )
}
