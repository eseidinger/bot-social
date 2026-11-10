import { MantineProvider } from '@mantine/core'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('./api', () => ({
  client: {
    GET: vi.fn(async () => ({
      data: localStorage.getItem('bot-social-group-names')?.split(/\s+/).includes('moderator')
        ? ['moderator']
        : [],
    })),
  },
}))
vi.mock('./pages/HomePage', () => ({ default: () => null }))
vi.mock('./pages/CasePage', () => ({
  default: ({ canModerate }: { canModerate: boolean }) => (
    <div>{canModerate ? 'Moderator controls visible' : 'Reader view'}</div>
  ),
}))

afterEach(() => localStorage.clear())

it('shows moderator controls after development group names are saved', async () => {
  const user = userEvent.setup()
  render(
    <MantineProvider>
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/cases/case-1']}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>
    </MantineProvider>,
  )

  expect(await screen.findByText('Reader view')).toBeInTheDocument()
  await user.type(screen.getByRole('textbox', { name: 'Development group names' }), 'moderator')
  expect(localStorage.getItem('bot-social-group-names')).toBe('moderator')
  expect(await screen.findByText('Moderator controls visible')).toBeInTheDocument()
})
