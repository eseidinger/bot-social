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
