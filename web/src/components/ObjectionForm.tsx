import { useState } from 'react'
import { Alert, Button, Textarea } from '@mantine/core'
import { explain } from '../api'

type Props = {
  onSubmit: (text: string) => Promise<void>
  pending: boolean
  error: unknown
}

export default function ObjectionForm({ onSubmit, pending, error }: Props) {
  const [text, setText] = useState('')

  async function submit() {
    try {
      await onSubmit(text.trim())
      setText('')
    } catch {
      // The mutation exposes its error through the parent prop.
    }
  }

  return (
    <div className="panel" style={{ marginTop: 16 }}>
      <Textarea
        label="Add an objection"
        minRows={2}
        value={text}
        onChange={(e) => setText(e.currentTarget.value)}
      />
      <Button mt="sm" onClick={submit} disabled={!text.trim()} loading={pending}>
        Post objection
      </Button>
      {error != null && (
        <Alert color="red" mt="sm">
          {explain(error)}
        </Alert>
      )}
    </div>
  )
}
