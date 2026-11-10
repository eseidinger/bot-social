import { MantineProvider } from '@mantine/core'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'
import { caseDetail, draft } from '../test/fixtures'
import VerdictEditor from './VerdictEditor'

it('requires a changed citation to be saved before publication', async () => {
  const user = userEvent.setup()
  const onSave = vi.fn().mockResolvedValue(undefined)
  const onPublish = vi.fn().mockResolvedValue(undefined)
  const props = {
    evidence: caseDetail.evidence,
    sources: caseDetail.sources,
    onSave,
    onPublish,
    saving: false,
    publishing: false,
    reviewActive: false,
    error: null,
  }
  const { rerender } = render(
    <MantineProvider>
      <VerdictEditor draft={draft} {...props} />
    </MantineProvider>,
  )

  const publish = screen.getByRole('button', { name: 'Publish saved draft' })
  await user.click(screen.getByRole('button', { name: 'Original report: page 1' }))
  expect(publish).toBeDisabled()
  await user.click(screen.getByRole('button', { name: 'Save draft' }))
  await waitFor(() => expect(onSave).toHaveBeenCalledWith(draft.text, ['evidence-1', 'evidence-2']))

  rerender(
    <MantineProvider>
      <VerdictEditor draft={{ ...draft, evidence_ids: ['evidence-1', 'evidence-2'] }} {...props} />
    </MantineProvider>,
  )
  expect(publish).toBeEnabled()
  await user.click(publish)
  await waitFor(() => expect(onPublish).toHaveBeenCalledOnce())
})

it('blocks publication while a review job is active', () => {
  render(
    <MantineProvider>
      <VerdictEditor
        draft={draft}
        evidence={caseDetail.evidence}
        sources={caseDetail.sources}
        onSave={vi.fn()}
        onPublish={vi.fn()}
        saving={false}
        publishing={false}
        reviewActive
        error={null}
      />
    </MantineProvider>,
  )
  expect(screen.getByRole('button', { name: 'Publish saved draft' })).toBeDisabled()
})
