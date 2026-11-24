import { useState } from 'react'
import { api, contentText, type Message } from '@/api'
import { Placeholders } from '@/components/highlight'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'

const SAMPLE: Message[] = [
  { role: 'system', content: 'You are hermes, a helpful assistant.' },
  { role: 'user', content: 'Write Julia Hartmann a mail at julia.hartmann@example.org saying Tobias Brenner will be in Konstanz tomorrow.' },
  { role: 'assistant', content: '', tool_calls: [{ function: { name: 'send_mail', arguments: '{"to":"julia.hartmann@example.org","body":"Hello Julia Hartmann"}' } }] },
]

export function PreviewView() {
  const [json, setJson] = useState(JSON.stringify(SAMPLE, null, 2))
  const [res, setRes] = useState<Awaited<ReturnType<typeof api.preview>> | null>(null)
  const [err, setErr] = useState('')

  async function run() {
    setErr('')
    try {
      const parsed = JSON.parse(json)
      setRes(await api.preview(Array.isArray(parsed) ? parsed : parsed.messages))
    } catch (e) { setErr(String(e)) }
  }

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>Request preview</CardTitle>
          <CardDescription>
            Paste a messages array (or a whole body). Shows the body after pseudonymize_body and the placeholder note,
            without sending anything to the upstream. Only the roles in PSEUDO_ROLES are pseudonymized.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea rows={20} className="font-mono text-xs" value={json} onChange={(e) => setJson(e.target.value)} />
          <div className="flex items-center gap-2">
            <Button onClick={run}>Preview</Button>
            {res && <span className="text-sm text-muted-foreground">{res.ms} ms</span>}
            {err && <span className="text-sm text-destructive">{err}</span>}
          </div>
        </CardContent>
      </Card>
      {res && (
        <Card>
          <CardHeader>
            <CardTitle>Sent to the upstream like this</CardTitle>
            <CardDescription>Mapping: {Object.entries(res.mapping).map(([k, v]) => `${k}=${v}`).join(', ') || 'empty'}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            {res.body.messages.map((m, i) => (
              <div key={i} className="rounded-lg border p-3">
                <Badge variant={m.role === 'user' ? 'default' : 'outline'} className="mb-2">{m.role}</Badge>
                <Placeholders text={contentText(m.content)} mapping={res.mapping} />
                {m.tool_calls?.map((tc, j) => (
                  <div key={j} className="mt-2 rounded bg-muted p-2 text-xs">
                    {tc.function?.name}(<Placeholders text={tc.function?.arguments ?? ''} mapping={res.mapping} />)
                  </div>
                ))}
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
