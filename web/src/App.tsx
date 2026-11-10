import { useState } from 'react'
import { Container, Group, TextInput } from '@mantine/core'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, Route, Routes } from 'react-router-dom'
import { client } from './api'
import CasePage from './pages/CasePage'
import HomePage from './pages/HomePage'

export default function App() {
  const queryClient = useQueryClient()
  const [groupNames, setGroupNames] = useState(() =>
    import.meta.env.DEV ? localStorage.getItem('bot-social-group-names') || '' : '',
  )
  const roles = useQuery({
    queryKey: ['roles'],
    queryFn: async () => {
      const { data, error } = await client.GET('/api/roles')
      if (error) throw error
      return data
    },
  })

  function updateGroupNames(value: string) {
    setGroupNames(value)
    localStorage.setItem('bot-social-group-names', value)
    void queryClient.invalidateQueries({ queryKey: ['roles'] })
  }

  return (
    <Container className="shell">
      <Group justify="space-between" mb="xl">
        <Link to="/" className="brand">
          BOT SOCIAL
        </Link>
        {import.meta.env.DEV && (
          <TextInput
            aria-label="Development group names"
            placeholder="Group names for local development"
            value={groupNames}
            onChange={(event) => updateGroupNames(event.currentTarget.value)}
          />
        )}
      </Group>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route
          path="/cases/:id"
          element={<CasePage canModerate={roles.data?.includes('moderator') ?? false} />}
        />
      </Routes>
    </Container>
  )
}
