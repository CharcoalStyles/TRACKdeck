import { Link } from 'react-router-dom'
import Card from '../components/Card'
import CapturesList from '../components/captures/CapturesList'
import TodayPane from '../components/today/TodayPane'

export default function HomePage() {
  return (
    <div className="grid w-full grid-cols-1 content-start gap-4 md:grid-cols-2">
      <TodayPane />
      <Card className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-lg font-semibold">Captures</h2>
          <Link to="/captures" className="text-sm text-accent hover:underline">
            Earlier days
          </Link>
        </div>
        <CapturesList days={2} />
      </Card>
    </div>
  )
}
