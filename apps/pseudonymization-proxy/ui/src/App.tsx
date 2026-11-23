import { useEffect, useState } from 'react'
import { api, type Config } from '@/api'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { TooltipProvider } from '@/components/ui/tooltip'
import { AuditView } from '@/views/audit'
import { DetectView } from '@/views/detect'
import { PreviewView } from '@/views/preview'
import { StatusView } from '@/views/status'

export default function App() {
  const [cfg, setCfg] = useState<Config | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    const load = () => api.config().then((c) => { setCfg(c); setErr('') }).catch((e) => setErr(String(e)))
    load()
    const t = setInterval(load, 10000)
    return () => clearInterval(t)
  }, [])

  return (
    <TooltipProvider>
      <div className="mx-auto max-w-[1600px] space-y-4 p-4 md:p-6">
        <header className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold">Pseudonymization proxy</h1>
          {cfg && <>
            <Badge variant={cfg.pii.ok ? 'secondary' : 'destructive'}>PII {cfg.pii.ok ? 'ok' : 'down'}</Badge>
            <span className="text-sm text-muted-foreground">:{cfg.port} → {cfg.upstream}</span>
            <span className="text-sm text-muted-foreground">{cfg.stats.requests ?? 0} requests since start</span>
          </>}
          {err && <Badge variant="destructive">Proxy unreachable: {err}</Badge>}
        </header>
        <Tabs defaultValue="audit">
          <TabsList>
            <TabsTrigger value="audit">Audit</TabsTrigger>
            <TabsTrigger value="detect">Detection</TabsTrigger>
            <TabsTrigger value="preview">Request preview</TabsTrigger>
            <TabsTrigger value="status">Status</TabsTrigger>
          </TabsList>
          <TabsContent value="audit" className="pt-3"><AuditView /></TabsContent>
          <TabsContent value="detect" className="pt-3"><DetectView defaultThreshold={cfg?.threshold} /></TabsContent>
          <TabsContent value="preview" className="pt-3"><PreviewView /></TabsContent>
          <TabsContent value="status" className="pt-3"><StatusView cfg={cfg} /></TabsContent>
        </Tabs>
      </div>
    </TooltipProvider>
  )
}
