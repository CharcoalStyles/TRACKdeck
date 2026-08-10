interface ToggleProps {
  checked: boolean
  onChange: (checked: boolean) => void
  label: string
  sublabel?: string
}

export default function Toggle({ checked, onChange, label, sublabel }: ToggleProps) {
  return (
    <label className="flex cursor-pointer items-center justify-between gap-4 py-2">
      <div>
        <div className="text-sm font-medium text-text-primary">{label}</div>
        {sublabel && <div className="text-xs text-text-muted">{sublabel}</div>}
      </div>
      <span className="relative inline-block h-6 w-11 shrink-0">
        <input
          type="checkbox"
          checked={checked}
          onChange={(e) => onChange(e.target.checked)}
          className="peer sr-only"
        />
        <span className="absolute inset-0 rounded-full bg-card-alt transition-colors peer-checked:bg-accent" />
        <span className="absolute left-0.5 top-0.5 h-5 w-5 rounded-full bg-white transition-transform peer-checked:translate-x-5" />
      </span>
    </label>
  )
}
