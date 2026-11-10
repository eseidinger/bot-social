import { MantineProvider } from '@mantine/core'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { expect, it, vi } from 'vitest'
import { caseDetail } from '../test/fixtures'
import CaseOverview from './CaseOverview'

it('links a published verdict and review finding to their evidence passage', async () => {
  const user = userEvent.setup()
  const onObjection = vi.fn().mockResolvedValue(undefined)
  render(
    <MantineProvider>
      <MemoryRouter>
        <CaseOverview
          data={caseDetail}
          onObjection={onObjection}
          objectionPending={false}
          objectionError={null}
        />
      </MemoryRouter>
    </MantineProvider>,
  )

  expect(screen.getByText('Cites or derives from: Original report')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'View passage' })).toHaveAttribute(
    'href',
    '#evidence-evidence-1',
  )
  expect(screen.getByRole('link', { name: 'Evidence evidence' })).toHaveAttribute(
    'href',
    '#evidence-evidence-1',
  )
  await user.type(
    screen.getByRole('textbox', { name: 'Add an objection' }),
    'The report needs an independent test.',
  )
  await user.click(screen.getByRole('button', { name: 'Post objection' }))
  await waitFor(() =>
    expect(onObjection).toHaveBeenCalledWith('The report needs an independent test.'),
  )
  await waitFor(() =>
    expect(screen.getByRole('textbox', { name: 'Add an objection' })).toHaveValue(''),
  )
})

it('shows queued and running web research states', () => {
  const props = {
    data: {
      ...caseDetail,
      status: 'submitted',
      sources: [],
      evidence: [],
      findings: [],
      verdicts: [],
      jobs: [{ id: 'job-1', kind: 'research', status: 'pending', attempts: 0, error: null }],
    },
    onObjection: vi.fn().mockResolvedValue(undefined),
    objectionPending: false,
    objectionError: null,
  }
  const { rerender } = render(
    <MantineProvider>
      <MemoryRouter>
        <CaseOverview {...props} />
      </MemoryRouter>
    </MantineProvider>,
  )
  expect(screen.getByText(/research job is queued/i)).toBeInTheDocument()

  rerender(
    <MantineProvider>
      <MemoryRouter>
        <CaseOverview
          {...props}
          data={{ ...props.data, jobs: [{ ...props.data.jobs[0], status: 'running' }] }}
        />
      </MemoryRouter>
    </MantineProvider>,
  )
  expect(screen.getByText(/fetching the submitted URL/i)).toBeInTheDocument()
})

it('shows fetch notes and the next moderator action when evidence is missing', () => {
  render(
    <MantineProvider>
      <MemoryRouter>
        <CaseOverview
          data={{
            ...caseDetail,
            status: 'awaiting_evidence',
            sources: [],
            evidence: [],
            findings: [],
            verdicts: [],
            jobs: [{ id: 'job-1', kind: 'research', status: 'done', attempts: 1, error: null }],
            posts: [
              {
                id: 'note-1',
                kind: 'research_note',
                text: 'Submitted URL could not be fetched: Source returned HTTP 404',
                created_at: caseDetail.created_at,
              },
            ],
          }}
          canModerate
          onObjection={vi.fn().mockResolvedValue(undefined)}
          objectionPending={false}
          objectionError={null}
        />
      </MemoryRouter>
    </MantineProvider>,
  )
  expect(screen.getByText(/research finished without a cited passage/i)).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Go to moderator actions' })).toHaveAttribute(
    'href',
    '#moderator-workspace',
  )
  expect(screen.getAllByText(/Source returned HTTP 404/).length).toBeGreaterThan(0)
})

it('lists researched sources and their cited passage counts', () => {
  render(
    <MantineProvider>
      <MemoryRouter>
        <CaseOverview
          data={{
            ...caseDetail,
            jobs: [{ id: 'job-1', kind: 'research', status: 'done', attempts: 1, error: null }],
          }}
          onObjection={vi.fn().mockResolvedValue(undefined)}
          objectionPending={false}
          objectionError={null}
        />
      </MemoryRouter>
    </MantineProvider>,
  )
  expect(screen.getByText('This case has 2 sources and 2 cited passages.')).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'Original report ↗' })).toHaveAttribute(
    'href',
    'https://example.org/report',
  )
})
