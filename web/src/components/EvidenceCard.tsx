import { Anchor, Card, Group, Text } from '@mantine/core'
import type { CaseDetail, Evidence } from '../types'

export default function EvidenceCard({
  item,
  sources,
}: {
  item: Evidence
  sources: CaseDetail['sources']
}) {
  const source = sources.find((candidate) => candidate.id === item.source_id)
  const original = sources.find((candidate) => candidate.id === source?.original_source_id)
  return (
    <Card withBorder id={`evidence-${item.id}`}>
      <Group justify="space-between">
        <Text fw={700}>{source?.title || 'Source'}</Text>
        <Text size="sm" className="muted">
          {item.locator}
        </Text>
      </Group>
      {source?.url && (
        <Anchor href={source.url} target="_blank" rel="noreferrer">
          Open source ↗
        </Anchor>
      )}
      {original && (
        <Text size="sm" className="muted">
          Cites or derives from: {original.title}
        </Text>
      )}
      <p className="passage">{item.passage}</p>
    </Card>
  )
}
