import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { client } from '../api'
import { caseDetail } from '../test/fixtures'
import ModeratorWorkspace from './ModeratorWorkspace'

vi.mock('../api', () => ({
  client: { POST: vi.fn().mockResolvedValue({ data: {} }) },
  explain: () => 'Request failed',
}))

it('lets a moderator retry a failed research job', async () => {
  const user = userEvent.setup()
  const onChanged = vi.fn()
  render(
    <MantineProvider>
      <QueryClientProvider client={new QueryClient()}>
        <ModeratorWorkspace
          data={{
            ...caseDetail,
            status: 'submitted',
            verdicts: [],
            jobs: [
              {
                id: 'research-1',
                kind: 'research',
                status: 'failed',
                attempts: 3,
                error: 'failed',
              },
            ],
          }}
          onChanged={onChanged}
        />
      </QueryClientProvider>
    </MantineProvider>,
  )

  await user.click(screen.getByRole('button', { name: 'Retry failed research' }))
  await waitFor(() =>
    expect(client.POST).toHaveBeenCalledWith('/api/cases/{case_id}/research/retry', {
      params: { path: { case_id: caseDetail.id } },
    }),
  )
  await waitFor(() => expect(onChanged).toHaveBeenCalledOnce())
})
