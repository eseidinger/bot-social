import { afterEach, expect, it, vi } from 'vitest'
import { client } from './api'

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

it('sends development group names from localStorage on API requests', async () => {
  const requests: Request[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      requests.push(request)
      return new Response(JSON.stringify(['moderator']), {
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )

  localStorage.setItem('bot-social-group-names', 'reader moderator')
  await client.GET('/api/roles')
  expect(requests[0].headers.get('X-Platform-Principal-Group-Names')).toBe('reader moderator')

  localStorage.removeItem('bot-social-group-names')
  await client.GET('/api/roles')
  expect(requests[1].headers.has('X-Platform-Principal-Group-Names')).toBe(false)
})

it('copies the platform CSRF cookie to state-changing requests', async () => {
  const requests: Request[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (request: Request) => {
      requests.push(request)
      return new Response(JSON.stringify({ id: 'case-1' }), {
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
  vi.spyOn(document, 'cookie', 'get').mockReturnValue('__Host-platform-csrf=csrf-value')

  await client.POST('/api/cases', { body: { claim: 'A sufficiently long test claim.' } })
  expect(requests[0].headers.get('X-Platform-CSRF-Token')).toBe('csrf-value')
})
