import { useState, type FormEvent } from 'react'
import { useLogin } from '../hooks/useAuth'

export default function LoginPage() {
  const [password, setPassword] = useState('')
  const login = useLogin()

  function handleSubmit(e: FormEvent) {
    e.preventDefault()
    login.mutate(password)
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-base px-4">
      <form
        onSubmit={handleSubmit}
        className="w-full max-w-sm rounded-lg border border-border bg-card p-6 shadow-lg"
      >
        <h1 className="mb-4 text-lg font-semibold text-text-primary">Log in</h1>
        <input
          type="password"
          autoFocus
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="Password"
          className="mb-3 w-full rounded border border-border bg-card-alt px-3 py-2 text-text-primary outline-none focus:border-accent"
        />
        <button
          type="submit"
          disabled={login.isPending || !password}
          className="w-full rounded bg-accent px-3 py-2 font-medium text-base transition-colors hover:bg-accent-hover disabled:opacity-50"
        >
          {login.isPending ? 'Logging in…' : 'Log in'}
        </button>
        {login.isError && (
          <p className="mt-3 text-sm text-danger">{login.error.message}</p>
        )}
      </form>
    </div>
  )
}
