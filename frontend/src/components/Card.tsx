import type { HTMLAttributes } from 'react'

export default function Card({ className = '', ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={`rounded-lg border border-border bg-card p-6 ${className}`}
      {...props}
    />
  )
}
