import { Alert, Anchor, Badge, Card, Group, Stack, Text, Title } from '@mantine/core'
import type { CaseDetail } from '../types'

export default function ResearchStatus({
  data,
  canModerate,
}: {
  data: CaseDetail
  canModerate: boolean
}) {
  const activeJob = data.jobs.find((job) => job.status === 'pending' || job.status === 'running')
  const researchNotes = data.posts.filter((post) => post.kind === 'research_note')
  let activeMessage = ''
  if (activeJob?.status === 'pending') {
    activeMessage = `${activeJob.kind} job is queued.`
  } else if (activeJob?.kind === 'research') {
    activeMessage = data.source_url
      ? 'Fetching the submitted URL and searching for further sources when a web-enabled model is configured.'
      : 'Examining the claim and searching for sources when a web-enabled model is configured.'
  } else if (activeJob?.kind === 'review') {
    activeMessage = 'Reviewing the collected passages.'
  } else if (activeJob?.kind === 'editorial') {
    activeMessage = 'Drafting a verdict from the reviewed evidence.'
  }

  return (
    <section>
      <Title order={2} mb="sm">
        Research progress
      </Title>
      {activeJob && (
        <Alert color="blue" mb="sm">
          {activeMessage} This page refreshes automatically.
        </Alert>
      )}
      {data.status === 'awaiting_evidence' && (
        <Alert color="yellow" mb="sm">
          Research finished without a cited passage. A moderator can add a source passage and run
          review.
          {canModerate && (
            <>
              {' '}
              <Anchor href="#moderator-workspace">Go to moderator actions</Anchor>
            </>
          )}
        </Alert>
      )}
      {data.status === 'draft' && canModerate && (
        <Alert color="green" mb="sm">
          A verdict draft is ready. <Anchor href="#moderator-workspace">Review the draft</Anchor>
        </Alert>
      )}
      {data.sources.length > 0 && (
        <Text className="muted" mb="sm">
          This case has {data.sources.length} source{data.sources.length === 1 ? '' : 's'} and{' '}
          {data.evidence.length} cited passage{data.evidence.length === 1 ? '' : 's'}.
        </Text>
      )}
      {researchNotes.map((note) => (
        <Alert color="yellow" key={note.id} mb="sm">
          {note.text}
        </Alert>
      ))}
      {data.sources.length > 0 && (
        <Stack gap="xs">
          {data.sources.map((source) => {
            const passageCount = data.evidence.filter((item) => item.source_id === source.id).length
            return (
              <Card withBorder key={source.id}>
                <Group justify="space-between">
                  {source.url ? (
                    <Anchor href={source.url} target="_blank" rel="noreferrer">
                      {source.title} ↗
                    </Anchor>
                  ) : (
                    <Text>{source.title}</Text>
                  )}
                  <Badge variant="light">
                    {passageCount} passage{passageCount === 1 ? '' : 's'}
                  </Badge>
                </Group>
              </Card>
            )
          })}
        </Stack>
      )}
    </section>
  )
}
