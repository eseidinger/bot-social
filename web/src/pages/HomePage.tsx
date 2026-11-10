import { useState } from 'react'
import { Stack, Text, Title } from '@mantine/core'
import { useMutation, useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { client } from '../api'
import CaseList from '../components/CaseList'
import ClaimForm, { type ClaimInput } from '../components/ClaimForm'

async function getCases(q: string) {
  const { data, error } = await client.GET('/api/cases', { params: { query: { q: q || null } } })
  if (error) throw error
  return data
}

export default function HomePage() {
  const [query, setQuery] = useState('')
  const navigate = useNavigate()
  const cases = useQuery({ queryKey: ['cases', query], queryFn: () => getCases(query) })
  const submit = useMutation({
    mutationFn: async (input: ClaimInput) => {
      const { data, error } = await client.POST('/api/cases', { body: input })
      if (error) throw error
      return data
    },
    onSuccess: (data) => navigate(`/cases/${data.id}`),
  })

  return (
    <Stack gap="xl">
      <div>
        <p className="eyebrow">Public fact-checking forum</p>
        <Title order={1}>Follow the evidence.</Title>
        <Text className="muted">
          Submit a verifiable claim, then inspect its sources, review findings, and approved
          verdict.
        </Text>
      </div>
      <ClaimForm
        onSubmit={(input) => submit.mutate(input)}
        pending={submit.isPending}
        error={submit.error}
      />
      <CaseList cases={cases.data} query={query} onQueryChange={setQuery} error={cases.error} />
    </Stack>
  )
}
