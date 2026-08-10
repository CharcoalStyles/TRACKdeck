import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'

// GET /settings doubles as the session probe — same idiom as today's
// static/js/auth.js's requireSession(), no dedicated "am I logged in"
// endpoint needed. staleTime means client-side navigations within the
// SPA don't re-probe on every route change, only cold loads/reloads.
export function useSessionProbe() {
  return useQuery({
    queryKey: ['session-probe'],
    queryFn: async () => {
      const { response } = await api.GET('/settings')
      if (response.status === 401) return { authenticated: false as const }
      return { authenticated: true as const }
    },
    staleTime: 5 * 60 * 1000,
    retry: false,
  })
}

export function useLogin() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  return useMutation({
    mutationFn: async (password: string) => {
      const { error } = await api.POST('/login', { body: { password } })
      if (error) throw new Error('Incorrect password')
    },
    onSuccess: () => {
      queryClient.setQueryData(['session-probe'], { authenticated: true })
      navigate('/')
    },
  })
}

export function useLogout() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  return useMutation({
    mutationFn: async () => {
      await api.POST('/logout')
    },
    onSuccess: () => {
      queryClient.setQueryData(['session-probe'], { authenticated: false })
      navigate('/login')
    },
  })
}
