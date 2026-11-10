import type { CaseDetail, Verdict } from '../types'

export const draft: Verdict = {
  id: 'verdict-1',
  revision: 1,
  status: 'draft',
  text: 'The claim remains unverified.',
  evidence_ids: ['evidence-1'],
  created_at: '2026-11-10T12:00:00Z',
  published_at: null,
}

export const caseDetail: CaseDetail = {
  id: 'case-1',
  claim: 'The motor runs without power.',
  source_url: 'https://example.org/claim',
  status: 'published',
  created_at: '2026-11-10T12:00:00Z',
  subclaims: [{ id: 'subclaim-1', text: 'The motor needs no external input.' }],
  sources: [
    {
      id: 'source-1',
      title: 'Original report',
      url: 'https://example.org/report',
      original_source_id: null,
    },
    {
      id: 'source-2',
      title: 'Reprinted article',
      url: 'https://example.org/reprint',
      original_source_id: 'source-1',
    },
  ],
  evidence: [
    {
      id: 'evidence-1',
      source_id: 'source-2',
      passage: 'The motor stopped when the battery was removed.',
      locator: 'page 2',
      captured_at: '2026-11-10T12:00:00Z',
    },
    {
      id: 'evidence-2',
      source_id: 'source-1',
      passage: 'The battery powered the motor.',
      locator: 'page 1',
      captured_at: '2026-11-10T12:00:00Z',
    },
  ],
  findings: [
    {
      id: 'finding-1',
      subclaim_id: 'subclaim-1',
      evidence_id: 'evidence-1',
      assessment: 'undermines',
      rationale: 'The motor stopped without the battery.',
    },
  ],
  verdicts: [{ ...draft, status: 'published', published_at: '2026-11-10T12:10:00Z' }],
  posts: [
    {
      id: 'post-1',
      kind: 'submission',
      text: 'The motor runs without power.',
      created_at: '2026-11-10T12:00:00Z',
    },
  ],
  jobs: [],
}
