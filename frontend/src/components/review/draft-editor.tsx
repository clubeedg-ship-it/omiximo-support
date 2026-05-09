import { useState, useEffect, useRef, useCallback } from 'react'
import { PenLine, AlertCircle, Sparkles, ChevronRight, ChevronDown, Loader2, Pencil } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { fetchDraftInsight, translateDraft, type InsightResponse } from '@/lib/api'

interface DraftEditorProps {
  threadId: string
  value: string
  onChange: (value: string) => void
  isEditable: boolean
  threadStatus: string
  targetLanguage: string
}

type InsightState =
  | { status: 'loading' }
  | { status: 'error' }
  | { status: 'done'; data: InsightResponse }

type EditFlowState =
  | { phase: 'idle' }
  | { phase: 'editing'; editText: string }
  | { phase: 'translating' }
  | { phase: 'done'; translatedText: string; correctionMade: boolean; correctionNote: string }
  | { phase: 'applied' }

interface DraftInsightCardProps {
  threadId: string
  onDraftUpdate: (newDraft: string) => void
  targetLanguage: string
}

function DraftInsightCard({ threadId, onDraftUpdate, targetLanguage }: DraftInsightCardProps) {
  const [state, setState] = useState<InsightState>({ status: 'loading' })
  const [translationOpen, setTranslationOpen] = useState(false)
  const [editFlow, setEditFlow] = useState<EditFlowState>({ phase: 'idle' })

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

  const handleEditClick = useCallback(() => {
    if (!insight?.translated_message) return
    setEditFlow({ phase: 'editing', editText: insight.translated_message })
  }, [insight])

  const handleEditCancel = useCallback(() => {
    setEditFlow({ phase: 'idle' })
  }, [])

  const handleEditSave = useCallback(async () => {
    if (editFlow.phase !== 'editing') return
    const englishText = editFlow.editText.trim()
    if (!englishText) return

    setEditFlow({ phase: 'translating' })

    try {
      const result = await translateDraft(threadId, {
        english_text: englishText,
        target_language: targetLanguage,
      })
      setEditFlow({
        phase: 'done',
        translatedText: result.translated_text ?? '',
        correctionMade: result.correction_made,
        correctionNote: result.correction_note,
      })
    } catch {
      // On error, return to idle so the user can try again; the translation
      // section still shows the original content.
      setEditFlow({ phase: 'idle' })
    }
  }, [editFlow, threadId, targetLanguage])

  const handleApplyToDraft = useCallback(() => {
    if (editFlow.phase !== 'done') return
    onDraftUpdate(editFlow.translatedText)
    setEditFlow({ phase: 'applied' })
    // Brief confirmation then reset to idle
    setTimeout(() => { setEditFlow({ phase: 'idle' }) }, 1500)
  }, [editFlow, onDraftUpdate])

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
            onClick={() => { setTranslationOpen((prev) => !prev) }}
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
              <div className="mt-2 border-t border-emerald-200 dark:border-emerald-700 pt-2 space-y-2">

                {/* idle: show translation text with edit icon */}
                {editFlow.phase === 'idle' && (
                  <div className="group relative">
                    <p className="text-sm leading-relaxed text-emerald-700 dark:text-emerald-300 bg-emerald-100/60 dark:bg-emerald-900/40 rounded px-3 py-2 whitespace-pre-wrap pr-8">
                      {insight?.translated_message}
                    </p>
                    <button
                      type="button"
                      onClick={handleEditClick}
                      title="Edit in your language"
                      aria-label="Edit translation"
                      className="absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity text-emerald-500 hover:text-emerald-600 dark:text-emerald-400 dark:hover:text-emerald-300 focus:opacity-100"
                    >
                      <Pencil className="h-3.5 w-3.5" aria-hidden="true" />
                    </button>
                  </div>
                )}

                {/* editing: textarea + Save / Cancel */}
                {editFlow.phase === 'editing' && (
                  <div className="space-y-2">
                    <Textarea
                      value={editFlow.editText}
                      onChange={(e) => {
                        setEditFlow({ phase: 'editing', editText: e.target.value })
                      }}
                      rows={4}
                      className="text-sm font-mono resize-none leading-relaxed bg-white dark:bg-slate-900"
                      aria-label="Edit English translation"
                    />
                    <div className="flex gap-2">
                      <Button
                        type="button"
                        size="sm"
                        onClick={() => { void handleEditSave() }}
                        className="bg-emerald-600 hover:bg-emerald-700 text-white"
                      >
                        Save
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        onClick={handleEditCancel}
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                )}

                {/* translating: spinner */}
                {editFlow.phase === 'translating' && (
                  <div className="flex items-center gap-2 text-sm text-emerald-600 dark:text-emerald-400 py-1">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
                    <span>Translating and verifying...</span>
                  </div>
                )}

                {/* done: result + badges + apply button */}
                {editFlow.phase === 'done' && (
                  <div className="space-y-2">
                    <p className="text-sm leading-relaxed text-emerald-700 dark:text-emerald-300 bg-emerald-100/60 dark:bg-emerald-900/40 rounded px-3 py-2 whitespace-pre-wrap">
                      {editFlow.translatedText}
                    </p>
                    <div className="flex items-center gap-2 flex-wrap">
                      {editFlow.correctionMade ? (
                        <Badge
                          variant="outline"
                          className="text-amber-700 border-amber-400 bg-amber-50 dark:text-amber-300 dark:border-amber-600 dark:bg-amber-900/30 text-xs cursor-default"
                          title={editFlow.correctionNote}
                        >
                          Correction applied
                        </Badge>
                      ) : (
                        <Badge
                          variant="outline"
                          className="text-emerald-700 border-emerald-400 bg-emerald-50 dark:text-emerald-300 dark:border-emerald-600 dark:bg-emerald-900/30 text-xs"
                        >
                          Verified
                        </Badge>
                      )}
                      <Button
                        type="button"
                        size="sm"
                        onClick={handleApplyToDraft}
                        className="bg-emerald-600 hover:bg-emerald-700 text-white ml-auto"
                      >
                        Apply to draft
                      </Button>
                    </div>
                  </div>
                )}

                {/* applied: brief confirmation */}
                {editFlow.phase === 'applied' && (
                  <div className="flex items-center gap-2 text-sm text-emerald-600 dark:text-emerald-400 py-1">
                    <span>Applied</span>
                  </div>
                )}

              </div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export function DraftEditor({ threadId, value, onChange, isEditable, threadStatus, targetLanguage }: DraftEditorProps) {
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

        {hasDraft && (
          <DraftInsightCard
            threadId={threadId}
            onDraftUpdate={onChange}
            targetLanguage={targetLanguage}
          />
        )}

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
