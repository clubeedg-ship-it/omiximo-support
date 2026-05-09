import { useState, useEffect, useRef, useCallback } from 'react'
import { PenLine, AlertCircle, Sparkles, ChevronRight, ChevronDown, Loader2 } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { fetchDraftInsight, type InsightResponse } from '@/lib/api'

interface DraftEditorProps {
  threadId: string
  value: string
  onChange: (value: string) => void
  isEditable: boolean
  threadStatus: string
}

type InsightState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'done'; data: InsightResponse }

function DraftInsightCard({ threadId }: { threadId: string }) {
  const [state, setState] = useState<InsightState>({ status: 'loading' })
  const [translationOpen, setTranslationOpen] = useState(false)

  useEffect(() => {
    let cancelled = false

    fetchDraftInsight(threadId)
      .then((data) => {
        if (!cancelled) setState({ status: 'done', data })
      })
      .catch(() => {
        if (!cancelled) setState({ status: 'error' })
      })

    return () => { cancelled = true }
  }, [threadId])

  const insight = state.status === 'done' ? state.data : null
  const hasTranslation = Boolean(insight?.translated_message?.trim())

  if (state.status === 'done' && !insight?.summary) return null

  return (
    <div className="bg-emerald-50 border border-emerald-200 rounded-lg p-4 space-y-3 dark:bg-emerald-900/20 dark:border-emerald-800">
      <div className="flex items-center gap-2">
        <Sparkles className="h-4 w-4 text-emerald-500 dark:text-emerald-400 shrink-0" aria-hidden="true" />
        <span className="text-sm font-semibold text-emerald-800 dark:text-emerald-300">Draft Summary</span>
      </div>

      {state.status === 'loading' && (
        <div className="flex items-center gap-2 text-sm text-emerald-400 dark:text-emerald-500">
          <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
          <span>Summarizing draft...</span>
        </div>
      )}

      {state.status === 'error' && (
        <div className="flex items-center gap-2 text-sm text-slate-400 dark:text-slate-500">
          <AlertCircle className="h-3.5 w-3.5" aria-hidden="true" />
          <span>Draft summary unavailable</span>
        </div>
      )}

      {state.status === 'done' && insight?.summary && (
        <p className="text-sm leading-relaxed text-emerald-900 dark:text-emerald-200">
          {insight.summary}
        </p>
      )}

      {hasTranslation && (
        <div>
          <button
            type="button"
            onClick={() => setTranslationOpen((prev) => !prev)}
            className="flex items-center gap-1.5 text-xs font-medium text-emerald-600 hover:text-emerald-700 dark:text-emerald-400 dark:hover:text-emerald-300 transition-colors"
            aria-expanded={translationOpen}
            aria-controls="draft-translation-content"
          >
            {translationOpen ? (
              <ChevronDown className="h-3.5 w-3.5" aria-hidden="true" />
            ) : (
              <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
            )}
            {translationOpen ? 'Hide translation' : 'Show translation'}
          </button>

          {translationOpen && (
            <div id="draft-translation-content">
              <div className="mt-2 border-t border-emerald-200 dark:border-emerald-700 pt-2">
                <p className="text-sm leading-relaxed text-emerald-700 dark:text-emerald-300 bg-emerald-100/60 dark:bg-emerald-900/40 rounded px-3 py-2 whitespace-pre-wrap">
                  {insight?.translated_message}
                </p>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function DraftEditor({ threadId, value, onChange, isEditable, threadStatus }: DraftEditorProps) {
  const isReadOnly = !isEditable
  const hasDraft = value.trim().length > 0
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const autoResize = useCallback(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${el.scrollHeight}px`
  }, [])

  useEffect(() => { autoResize() }, [value, autoResize])

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="flex items-center gap-2 text-base">
          <PenLine className="h-4 w-4 text-slate-500" aria-hidden="true" />
          Drafted Response
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {isReadOnly && (
          <div className="flex items-center gap-2 rounded-md bg-amber-50 border border-amber-200 px-3 py-2 dark:bg-amber-900/20 dark:border-amber-700" role="alert">
            <AlertCircle className="h-4 w-4 text-amber-600 shrink-0" aria-hidden="true" />
            <p className="text-xs text-amber-700 dark:text-amber-300">
              This thread is <strong>{threadStatus}</strong> and cannot be edited.
            </p>
          </div>
        )}

        {!value && (
          <div className="rounded-md bg-slate-50 border border-slate-200 px-3 py-2 dark:bg-slate-800/50 dark:border-slate-700" role="note">
            <p className="text-xs text-slate-500 dark:text-slate-400">
              No drafted response available. The system may not have generated one yet, or this is a Red-risk thread requiring manual composition.
            </p>
          </div>
        )}

        {hasDraft && <DraftInsightCard threadId={threadId} />}

        <div>
          <Label htmlFor="draft-response" className="sr-only">
            Draft response
          </Label>
          <Textarea
            ref={textareaRef}
            id="draft-response"
            value={value}
            onChange={(e) => { onChange(e.target.value) }}
            readOnly={isReadOnly}
            placeholder={isReadOnly ? 'No response drafted.' : 'Type the response to send to the customer...'}
            rows={3}
            className="resize-none overflow-hidden font-mono text-sm leading-relaxed"
            aria-label="Draft response to customer"
            aria-readonly={isReadOnly}
          />
        </div>

        <div className="flex items-center justify-between">
          <p className="text-xs text-slate-400 dark:text-slate-500">
            {value.length} character{value.length !== 1 ? 's' : ''}
          </p>
          {isEditable && (
            <p className="text-xs text-slate-400 dark:text-slate-500">
              Edit before approving to send
            </p>
          )}
        </div>
      </CardContent>
    </Card>
  )
}
