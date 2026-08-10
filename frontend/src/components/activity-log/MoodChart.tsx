import { useState } from 'react'
import { ACTIVITY_COLORS, CHART_INK, formatDay } from './activityColors'

export interface MoodPoint {
  date: string
  avg_mood: number
  count: number
}

interface LayoutPoint extends MoodPoint {
  x: number
  y: number
}

export interface MoodLayout {
  width: number
  height: number
  marginLeft: number
  marginRight: number
  points: LayoutPoint[]
  segments: LayoutPoint[][]
  yTicks: { value: number; y: number }[]
}

const DAY_MS = 86400000
const dayTime = (dateStr: string) => new Date(`${dateStr}T00:00:00`).getTime()

// Pure geometry — no DOM — so it's independently testable (plan's "known
// input, assert computed geometry" bar for the two hand-rolled charts).
export function computeMoodLayout(moodByDay: MoodPoint[], width = 640, height = 220): MoodLayout {
  const marginLeft = 28
  const marginRight = 16
  const marginTop = 16
  const marginBottom = 28
  const plotWidth = width - marginLeft - marginRight
  const plotHeight = height - marginTop - marginBottom

  const dates = moodByDay.map((d) => dayTime(d.date))
  const minDate = Math.min(...dates)
  const maxDate = Math.max(...dates)
  const dateSpan = Math.max(maxDate - minDate, DAY_MS)

  const xFor = (t: number) => marginLeft + ((t - minDate) / dateSpan) * plotWidth
  const yFor = (mood: number) => marginTop + (1 - (mood - 1) / 9) * plotHeight

  const points: LayoutPoint[] = moodByDay.map((p) => ({
    ...p,
    x: xFor(dayTime(p.date)),
    y: yFor(p.avg_mood),
  }))

  // Break the line wherever consecutive days-with-data aren't adjacent
  // calendar days, so a gap in logging reads as a gap, not an
  // interpolated trend across missing days.
  const segments: LayoutPoint[][] = []
  let segment: LayoutPoint[] = []
  points.forEach((point, i) => {
    if (segment.length > 0 && dayTime(point.date) - dayTime(points[i - 1].date) > DAY_MS) {
      segments.push(segment)
      segment = []
    }
    segment.push(point)
  })
  if (segment.length > 0) segments.push(segment)

  const yTicks = [1, 5, 10].map((value) => ({ value, y: yFor(value) }))

  return { width, height, marginLeft, marginRight, points, segments, yTicks }
}

export default function MoodChart({ moodByDay }: { moodByDay: MoodPoint[] }) {
  const [hovered, setHovered] = useState<number | null>(null)

  if (moodByDay.length === 0) {
    return (
      <p className="text-sm italic text-text-muted">
        Not enough data yet — log a few entries with a mood/energy level to see this chart.
      </p>
    )
  }

  const { width, height, marginLeft, marginRight, points, segments, yTicks } = computeMoodLayout(moodByDay)
  const lineColor = ACTIVITY_COLORS.Meal
  const hoveredPoint = hovered !== null ? points[hovered] : null

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Mood and energy level over time, scale 1 to 10"
        className="w-full"
      >
        {yTicks.map(({ value, y }) => (
          <g key={value}>
            <line x1={marginLeft} x2={width - marginRight} y1={y} y2={y} stroke={CHART_INK.grid} strokeWidth={1} />
            <text x={marginLeft - 8} y={y + 3} textAnchor="end" fontSize={10} fill={CHART_INK.muted}>
              {value}
            </text>
          </g>
        ))}

        <text x={marginLeft} y={height - 8} textAnchor="start" fontSize={10} fill={CHART_INK.muted}>
          {formatDay(moodByDay[0].date)}
        </text>
        <text x={width - marginRight} y={height - 8} textAnchor="end" fontSize={10} fill={CHART_INK.muted}>
          {formatDay(moodByDay[moodByDay.length - 1].date)}
        </text>

        {segments.map(
          (seg, i) =>
            seg.length > 1 && (
              <polyline
                key={i}
                points={seg.map((p) => `${p.x},${p.y}`).join(' ')}
                fill="none"
                stroke={lineColor}
                strokeWidth={2}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ),
        )}

        {points.map((point, i) => (
          <g key={i}>
            <circle cx={point.x} cy={point.y} r={hovered === i ? 8 : 6} fill={lineColor} stroke="#1e1e1e" strokeWidth={2} />
            <circle
              cx={point.x}
              cy={point.y}
              r={12}
              fill="transparent"
              className="cursor-pointer"
              onPointerEnter={() => setHovered(i)}
              onPointerLeave={() => setHovered(null)}
            />
          </g>
        ))}
      </svg>

      {hoveredPoint && (
        <div
          className="pointer-events-none absolute -translate-x-1/2 -translate-y-full rounded border border-border bg-card px-2 py-1 text-xs shadow-lg"
          style={{ left: `${(hoveredPoint.x / width) * 100}%`, top: `${(hoveredPoint.y / height) * 100}%` }}
        >
          <div className="font-semibold text-text-primary">{hoveredPoint.avg_mood} / 10</div>
          <div className="text-text-muted">
            {formatDay(hoveredPoint.date)} · {hoveredPoint.count} {hoveredPoint.count === 1 ? 'entry' : 'entries'}
          </div>
        </div>
      )}
    </div>
  )
}
