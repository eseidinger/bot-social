import { Alert, Badge, Card, Group, Stack, Text, TextInput, Title } from '@mantine/core'
import { Link } from 'react-router-dom'
import { explain } from '../api'
import type { CaseSummary } from '../types'

type Props = {
  cases: CaseSummary[] | undefined
  query: string
  onQueryChange: (value: string) => void
  error: unknown
}

export default function CaseList({ cases, query, onQueryChange, error }: Props) {
  return (
    <div>
      <Title order={2} mb="md">
        Cases
      </Title>
      <TextInput
        aria-label="Search cases"
        placeholder="Search claims and evidence"
        value={query}
        onChange={(e) => onQueryChange(e.currentTarget.value)}
      />
      {error != null && (
        <Alert color="red" mt="md">
          {explain(error)}
        </Alert>
      )}
      <Stack mt="md">
        {cases?.map((item) => (
          <Card key={item.id} withBorder component={Link} to={`/cases/${item.id}`}>
            <Group justify="space-between">
              <Text fw={600}>{item.claim}</Text>
              <Badge>{item.status.replace('_', ' ')}</Badge>
            </Group>
          </Card>
        ))}
      </Stack>
    </div>
  )
}
