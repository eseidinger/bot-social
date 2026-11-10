import { MantineProvider } from '@mantine/core'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import ClaimForm from './ClaimForm'

it('submits a valid claim with its prepared source text', async () => {
  const user = userEvent.setup()
  const onSubmit = vi.fn()
  render(
    <MantineProvider>
      <ClaimForm onSubmit={onSubmit} pending={false} error={null} />
    </MantineProvider>,
  )

  const submit = screen.getByRole('button', { name: 'Create fact-check thread' })
  expect(submit).toBeDisabled()
  await user.type(screen.getByRole('textbox', { name: 'Claim' }), 'The motor runs without power.')
  await user.type(
    screen.getByRole('textbox', { name: 'Source text (optional)' }),
    'The battery was removed.',
  )
  await user.click(submit)

  expect(onSubmit).toHaveBeenCalledWith({
    claim: 'The motor runs without power.',
    source_url: null,
    source_title: null,
    source_text: 'The battery was removed.',
  })
})
