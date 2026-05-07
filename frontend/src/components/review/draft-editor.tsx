import { PenLine, AlertCircle } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Textarea } from '@/components/ui/textarea'
import { Label } from '@/components/ui/label'

interface DraftEditorProps {
  value: string
  onChange: (value: string) => void
  isEditable: boolean
  threadStatus: string
}

export function DraftEditor({ value, onChange, isEditable, threadStatus }: DraftEditorProps) {
  const isReadOnly = !isEditable

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

        <div>
          <Label htmlFor="draft-response" className="sr-only">
            Draft response
          </Label>
          <Textarea
            id="draft-response"
            value={value}
            onChange={(e) => { onChange(e.target.value) }}
            readOnly={isReadOnly}
            placeholder={isReadOnly ? 'No response drafted.' : 'Type the response to send to the customer...'}
            rows={10}
            className="resize-none font-mono text-sm leading-relaxed"
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
