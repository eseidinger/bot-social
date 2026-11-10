import { Alert, Anchor, Badge, Card, Group, Stack, Text, Title } from '@mantine/core'
import { Link } from 'react-router-dom'
import type { CaseDetail } from '../types'
import EvidenceCard from './EvidenceCard'
import ObjectionForm from './ObjectionForm'
import ResearchStatus from './ResearchStatus'

type Props = {
  data: CaseDetail
  onObjection: (text: string) => Promise<void>
  objectionPending: boolean
  objectionError: unknown
  canModerate?: boolean
}

export default function CaseOverview({
  data,
  onObjection,
  objectionPending,
  objectionError,
  canModerate = false,
}: Props) {
  return (
    <>
      <div>
        <Link to="/">← All cases</Link>
        <p className="eyebrow">Fact-check thread</p>
        <Title order={1}>{data.claim}</Title>
        <Group mt="sm">
          <Badge>{data.status.replace('_', ' ')}</Badge>
          {data.source_url && (
            <Anchor href={data.source_url} target="_blank" rel="noreferrer">
              Submitted source ↗
            </Anchor>
          )}
        </Group>
      </div>
      <ResearchStatus data={data} canModerate={canModerate} />
      {data.jobs
        .filter((job) => job.status === 'failed')
        .map((job) => (
          <Alert color="red" key={job.id}>
            {job.kind} job failed: {job.error}
            {job.kind === 'research' && canModerate && (
              <>
                {' '}
                <Anchor href="#moderator-workspace">Retry research</Anchor>
              </>
            )}
          </Alert>
        ))}
      <section>
        <Title order={2} mb="sm">
          Subclaims
        </Title>
        <Stack>
          {data.subclaims.length ? (
            data.subclaims.map((item) => (
              <Card withBorder key={item.id}>
                {item.text}
              </Card>
            ))
          ) : (
            <Text className="muted">Research has not finished.</Text>
          )}
        </Stack>
      </section>
      <section>
        <Title order={2} mb="sm">
          Evidence
        </Title>
        <Stack>
          {data.evidence.map((item) => (
            <EvidenceCard key={item.id} item={item} sources={data.sources} />
          ))}
          {!data.evidence.length && (
            <Text className="muted">No source passages have been added yet.</Text>
          )}
        </Stack>
      </section>
      <section>
        <Title order={2} mb="sm">
          Review findings
        </Title>
        <Stack>
          {data.findings.map((finding) => (
            <Card withBorder key={finding.id}>
              <Badge
                color={
                  finding.assessment === 'supports'
                    ? 'green'
                    : finding.assessment === 'undermines'
                      ? 'red'
                      : 'gray'
                }
              >
                {finding.assessment}
              </Badge>
              <Text mt="sm">
                {data.subclaims.find((item) => item.id === finding.subclaim_id)?.text}
              </Text>
              <Text className="muted">{finding.rationale}</Text>
              <Anchor href={`#evidence-${finding.evidence_id}`}>View passage</Anchor>
            </Card>
          ))}
        </Stack>
      </section>
      <section>
        <Title order={2} mb="sm">
          Verdicts
        </Title>
        <Stack>
          {data.verdicts
            .filter((verdict) => verdict.status === 'published')
            .map((verdict) => (
              <Card withBorder key={verdict.id}>
                <Group justify="space-between">
                  <Text fw={700}>Revision {verdict.revision}</Text>
                  <Badge color="green">Published</Badge>
                </Group>
                <p className="verdict">{verdict.text}</p>
                <Group>
                  {verdict.evidence_ids.map((evidenceId) => (
                    <Anchor key={evidenceId} href={`#evidence-${evidenceId}`}>
                      Evidence {evidenceId.slice(0, 8)}
                    </Anchor>
                  ))}
                </Group>
              </Card>
            ))}
          {!data.verdicts.some((verdict) => verdict.status === 'published') && (
            <Text className="muted">No verdict has been approved yet.</Text>
          )}
        </Stack>
      </section>
      <section>
        <Title order={2} mb="sm">
          Thread
        </Title>
        <Stack>
          {data.posts.map((post) => (
            <Card withBorder key={post.id}>
              <Text size="sm" className="muted">
                {post.kind} · {new Date(post.created_at).toLocaleString()}
              </Text>
              <Text>{post.text}</Text>
            </Card>
          ))}
        </Stack>
        <ObjectionForm onSubmit={onObjection} pending={objectionPending} error={objectionError} />
      </section>
    </>
  )
}
