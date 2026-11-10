import { useState } from 'react'
import { Alert, Button, Divider, Group, Text, Textarea, Title } from '@mantine/core'
import { explain } from '../api'
import type { CaseDetail, Verdict } from '../types'

type Props = {
  draft: Verdict
  evidence: CaseDetail['evidence']
  sources: CaseDetail['sources']
  onSave: (text: string, evidenceIds: string[]) => Promise<void>
  onPublish: () => Promise<void>
  saving: boolean
  publishing: boolean
  reviewActive: boolean
  error: unknown
}

export default function VerdictEditor({
  draft,
  evidence,
  sources,
  onSave,
  onPublish,
  saving,
  publishing,
  reviewActive,
  error,
}: Props) {
  const [text, setText] = useState(draft.text)
  const [evidenceIds, setEvidenceIds] = useState(draft.evidence_ids)
  const hasUnsavedChanges =
    text !== draft.text ||
    evidenceIds.length !== draft.evidence_ids.length ||
    evidenceIds.some((id) => !draft.evidence_ids.includes(id))

  async function save() {
    try {
      await onSave(text.trim(), evidenceIds)
    } catch {
      // The mutation exposes its error through the parent prop.
    }
  }

  async function publish() {
    try {
      await onPublish()
    } catch {
      // The mutation exposes its error through the parent prop.
    }
  }

  return (
    <>
      <Divider my="xl" />
      <Title order={3}>Draft revision {draft.revision}</Title>
      <Text className="muted">
        Edit the draft, save it, and review its citations before publishing.
      </Text>
      <Textarea
        mt="md"
        minRows={6}
        label="Verdict text"
        value={text}
        onChange={(event) => setText(event.currentTarget.value)}
      />
      <Text fw={600} mt="md">
        Cited passages
      </Text>
      <Group mt="xs">
        {evidence.map((item) => (
          <Button
            key={item.id}
            size="xs"
            variant={evidenceIds.includes(item.id) ? 'filled' : 'outline'}
            onClick={() =>
              setEvidenceIds((ids) =>
                ids.includes(item.id) ? ids.filter((id) => id !== item.id) : [...ids, item.id],
              )
            }
          >
            {sources.find((source) => source.id === item.source_id)?.title}: {item.locator}
          </Button>
        ))}
      </Group>
      <Group mt="md">
        <Button onClick={save} disabled={!text.trim() || !hasUnsavedChanges} loading={saving}>
          Save draft
        </Button>
        <Button
          color="green"
          onClick={publish}
          disabled={hasUnsavedChanges || saving || reviewActive}
          loading={publishing}
        >
          Publish saved draft
        </Button>
      </Group>
      {error != null && (
        <Alert color="red" mt="sm">
          {explain(error)}
        </Alert>
      )}
    </>
  )
}
