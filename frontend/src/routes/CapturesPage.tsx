import Card from '../components/Card'
import CapturesList from '../components/captures/CapturesList'

export default function CapturesPage() {
  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col gap-4">
      <Card>
        <h2 className="mb-1 text-lg font-semibold">Captures</h2>
        <p className="mb-4 text-sm text-text-muted">
          Everything jotted down in the last 30 days, from voice, chat or here. Tick things off, fix the
          wording, or turn one into a reminder, a calendar event or a planning task.
        </p>
        <CapturesList days={30} />
      </Card>
    </div>
  )
}
