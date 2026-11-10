import { useState } from 'react'
import { Alert, Button, Stack, Textarea, TextInput, Title } from '@mantine/core'
import { explain } from '../api'

export type ClaimInput = {
  claim: string
  source_url: string | null
  source_title: string | null
  source_text: string | null
}

type Props = {
  onSubmit: (input: ClaimInput) => void
  pending: boolean
  error: unknown
}

export default function ClaimForm({ onSubmit, pending, error }: Props) {
  const [claim, setClaim] = useState('')
  const [url, setUrl] = useState('')
  const [sourceTitle, setSourceTitle] = useState('')
  const [sourceText, setSourceText] = useState('')

  return (
    <div className="panel">
      <Title order={3} mb="md">
        Submit a claim
      </Title>
      <Stack>
        <Textarea
          label="Claim"
          placeholder="State a specific, verifiable claim"
          minRows={3}
          value={claim}
          onChange={(e) => setClaim(e.currentTarget.value)}
        />
        <TextInput
          label="Source link (optional)"
          placeholder="https://…"
          value={url}
          onChange={(e) => setUrl(e.currentTarget.value)}
        />
        <TextInput
          label="Source title (optional)"
          value={sourceTitle}
          onChange={(e) => setSourceTitle(e.currentTarget.value)}
        />
        <Textarea
          label="Source text (optional)"
          description="Paste a source excerpt that the research job may quote exactly. A URL alone is not fetched automatically."
          minRows={4}
          value={sourceText}
          onChange={(e) => setSourceText(e.currentTarget.value)}
        />
        {error != null && <Alert color="red">{explain(error)}</Alert>}
        <Button
          onClick={() =>
            onSubmit({
              claim: claim.trim(),
              source_url: url || null,
              source_title: sourceTitle || null,
              source_text: sourceText || null,
            })
          }
          disabled={claim.trim().length < 10}
          loading={pending}
        >
          Create fact-check thread
        </Button>
      </Stack>
    </div>
  )
}
