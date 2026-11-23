import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { labelColor } from '@/api'
import { cn } from '@/lib/utils'

export type Span = { start: number; end: number; label: string; title?: string; className?: string }

/** Text with highlighted ranges (non-overlapping). */
export function Highlight({ text, spans }: { text: string; spans: Span[] }) {
  const sorted = [...spans].sort((a, b) => a.start - b.start)
  const out: React.ReactNode[] = []
  let pos = 0
  sorted.forEach((s, i) => {
    if (s.start < pos) return
    out.push(text.slice(pos, s.start))
    out.push(
      <Tooltip key={i}>
        <TooltipTrigger
          render={
            <mark className={cn('rounded px-0.5 ring-1', s.className ?? labelColor(s.label))}>
              {text.slice(s.start, s.end)}
            </mark>
          }
        />
        <TooltipContent>{s.title ?? s.label}</TooltipContent>
      </Tooltip>,
    )
    pos = s.end
  })
  out.push(text.slice(pos))
  return <div className="whitespace-pre-wrap break-words font-mono text-sm leading-relaxed">{out}</div>
}

const PH = /\[?\b([A-Z][A-Z0-9_]*?_\d+)\b\]?/g

/** Colorize placeholders such as [PERSON_1]. */
export function Placeholders({ text, mapping }: { text: string; mapping?: Record<string, string> }) {
  const spans: Span[] = []
  for (const m of text.matchAll(PH)) {
    const key = m[1]
    if (mapping && !(key in mapping)) continue
    spans.push({
      start: m.index!, end: m.index! + m[0].length, label: key,
      title: mapping ? `${key} = ${mapping[key]}` : key,
    })
  }
  return <Highlight text={text} spans={spans} />
}
