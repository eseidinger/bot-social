import { Alert, Stack, Text } from '@mantine/core'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { client, explain } from '../api'
import CaseOverview from '../components/CaseOverview'
import ModeratorWorkspace from '../components/ModeratorWorkspace'

async function getCase(id: string) {
  const { data, error } = await client.GET('/api/cases/{case_id}', {
    params: { path: { case_id: id } },
  })
  if (error) throw error
  return data
}

export default function CasePage({ canModerate }: { canModerate: boolean }) {
  const { id = '' } = useParams()
  const queryClient = useQueryClient()
  const query = useQuery({
    queryKey: ['case', id],
    queryFn: () => getCase(id),
    refetchInterval: (result) =>
      result.state.data?.jobs.some((job) => job.status === 'pending' || job.status === 'running')
        ? 2000
        : false,
  })
  const refresh = () => queryClient.invalidateQueries({ queryKey: ['case', id] })
  const objection = useMutation({
    mutationFn: async (text: string) => {
      const { error } = await client.POST('/api/cases/{case_id}/objections', {
        params: { path: { case_id: id } },
        body: { text },
      })
      if (error) throw error
    },
    onSuccess: refresh,
  })

  if (query.isLoading) return <Text>Loading case…</Text>
  if (query.error || !query.data) return <Alert color="red">{explain(query.error)}</Alert>

  return (
    <Stack gap="xl">
      <CaseOverview
        data={query.data}
        onObjection={(text) => objection.mutateAsync(text)}
        objectionPending={objection.isPending}
        objectionError={objection.error}
        canModerate={canModerate}
      />
      {canModerate && <ModeratorWorkspace data={query.data} onChanged={refresh} />}
    </Stack>
  )
}
