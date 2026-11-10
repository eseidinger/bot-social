import { useState } from 'react'
import {
  Alert,
  Button,
  Divider,
  Group,
  Select,
  Stack,
  Text,
  Textarea,
  TextInput,
  Title,
} from '@mantine/core'
import { useMutation } from '@tanstack/react-query'
import { client, explain } from '../api'
import type { CaseDetail } from '../types'
import VerdictEditor from './VerdictEditor'

type Props = {
  data: CaseDetail
  onChanged: () => void
}

export default function ModeratorWorkspace({ data, onChanged }: Props) {
  const [title, setTitle] = useState('')
  const [url, setUrl] = useState('')
  const [passage, setPassage] = useState('')
  const [locator, setLocator] = useState('')
  const [original, setOriginal] = useState<string | null>(null)
  const [correctedSource, setCorrectedSource] = useState<string | null>(null)
  const [correctionReason, setCorrectionReason] = useState('')
  const caseId = data.id
  const draft = data.verdicts.find((verdict) => verdict.status === 'draft')
  const active = data.jobs.some((job) => job.status === 'pending' || job.status === 'running')
  const failedResearch =
    data.status === 'submitted' &&
    data.jobs.some((job) => job.kind === 'research' && job.status === 'failed')

  const retryResearch = useMutation({
    mutationFn: async () => {
      const { error } = await client.POST('/api/cases/{case_id}/research/retry', {
        params: { path: { case_id: caseId } },
      })
      if (error) throw error
    },
    onSuccess: onChanged,
  })

  const addEvidence = useMutation({
    mutationFn: async () => {
      const { error } = await client.POST('/api/cases/{case_id}/evidence', {
        params: { path: { case_id: caseId } },
        body: { title, url: url || null, passage, locator, original_source_id: original },
      })
      if (error) throw error
    },
    onSuccess: () => {
      setTitle('')
      setUrl('')
      setPassage('')
      setLocator('')
      setOriginal(null)
      onChanged()
    },
  })
  const review = useMutation({
    mutationFn: async () => {
      const { error } = await client.POST('/api/cases/{case_id}/review', {
        params: { path: { case_id: caseId } },
      })
      if (error) throw error
    },
    onSuccess: onChanged,
  })
  const correction = useMutation({
    mutationFn: async () => {
      if (!correctedSource) throw new Error('Select a source')
      const { error } = await client.POST('/api/sources/{source_id}/corrections', {
        params: { path: { source_id: correctedSource } },
        body: { text: correctionReason },
      })
      if (error) throw error
    },
    onSuccess: () => {
      setCorrectionReason('')
      setCorrectedSource(null)
      onChanged()
    },
  })
  const save = useMutation({
    mutationFn: async ({
      verdictId,
      text,
      evidenceIds,
    }: {
      verdictId: string
      text: string
      evidenceIds: string[]
    }) => {
      const { error } = await client.PUT('/api/cases/{case_id}/verdicts/{verdict_id}', {
        params: { path: { case_id: caseId, verdict_id: verdictId } },
        body: { text, evidence_ids: evidenceIds },
      })
      if (error) throw error
    },
    onSuccess: onChanged,
  })
  const publish = useMutation({
    mutationFn: async (verdictId: string) => {
      const { error } = await client.POST('/api/cases/{case_id}/verdicts/{verdict_id}/publish', {
        params: { path: { case_id: caseId, verdict_id: verdictId } },
      })
      if (error) throw error
    },
    onSuccess: onChanged,
  })

  return (
    <section className="panel" id="moderator-workspace">
      <p className="eyebrow">Moderator workspace</p>
      {failedResearch && (
        <>
          <Button
            mb="md"
            onClick={() => retryResearch.mutate()}
            disabled={active}
            loading={retryResearch.isPending}
          >
            Retry failed research
          </Button>
          {retryResearch.error && <Alert color="red">{explain(retryResearch.error)}</Alert>}
        </>
      )}
      <Title order={2} mb="md">
        Add a source passage
      </Title>
      <Stack>
        <TextInput
          label="Source title"
          value={title}
          onChange={(event) => setTitle(event.currentTarget.value)}
        />
        <TextInput
          label="Source URL (optional)"
          value={url}
          onChange={(event) => setUrl(event.currentTarget.value)}
        />
        <Select
          label="Derived from an existing source (optional)"
          clearable
          data={data.sources.map((source) => ({ value: source.id, label: source.title }))}
          value={original}
          onChange={setOriginal}
        />
        <Textarea
          label="Exact passage"
          minRows={4}
          value={passage}
          onChange={(event) => setPassage(event.currentTarget.value)}
        />
        <TextInput
          label="Page, timestamp, or section locator"
          value={locator}
          onChange={(event) => setLocator(event.currentTarget.value)}
        />
        <Group>
          <Button
            onClick={() => addEvidence.mutate()}
            disabled={!title.trim() || !passage.trim() || !locator.trim()}
            loading={addEvidence.isPending}
          >
            Add evidence
          </Button>
          <Button
            variant="light"
            onClick={() => review.mutate()}
            disabled={!data.evidence.length || !data.subclaims.length || active}
            loading={review.isPending}
          >
            Run review
          </Button>
        </Group>
        {(addEvidence.error || review.error) && (
          <Alert color="red">{explain(addEvidence.error || review.error)}</Alert>
        )}
        <Divider my="lg" />
        <Title order={3}>Source correction</Title>
        <Text className="muted">
          Flag published verdicts that cite this source or a derived source for review.
        </Text>
        <Select
          label="Corrected source"
          clearable
          data={data.sources.map((source) => ({ value: source.id, label: source.title }))}
          value={correctedSource}
          onChange={setCorrectedSource}
        />
        <TextInput
          label="What changed?"
          value={correctionReason}
          onChange={(event) => setCorrectionReason(event.currentTarget.value)}
        />
        <Button
          variant="light"
          color="orange"
          disabled={!correctedSource || !correctionReason.trim()}
          loading={correction.isPending}
          onClick={() => correction.mutate()}
        >
          Flag affected verdicts
        </Button>
        {correction.error && <Alert color="red">{explain(correction.error)}</Alert>}
      </Stack>
      {draft && (
        <VerdictEditor
          key={draft.id}
          draft={draft}
          evidence={data.evidence}
          sources={data.sources}
          onSave={(text, evidenceIds) =>
            save.mutateAsync({ verdictId: draft.id, text, evidenceIds })
          }
          onPublish={() => publish.mutateAsync(draft.id)}
          saving={save.isPending}
          publishing={publish.isPending}
          reviewActive={active}
          error={save.error || publish.error}
        />
      )}
    </section>
  )
}
