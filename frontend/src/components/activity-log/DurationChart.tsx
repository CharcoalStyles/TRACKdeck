import { useState } from 'react'
import { ACTIVITY_COLORS, CHART_INK, formatMinutes } from './activityColors'

export interface DurationDatum {
  activity_type: string
  total_minutes: number
  entry_count: number
}

interface LayoutBar extends DurationDatum {
  bandCenter: number
  bandWidth: number
  barTop: number
  barHeight: number
  left: number
  right: number
  r: number
  color: string
}

export interface DurationLayout {
  width: number
  height: number
  marginLeft: number
  marginRight: number
  baselineY: number
  bars: LayoutBar[]
}

// Pure geometry — no DOM — independently testable per the plan's "known
// input, assert computed geometry" bar for the two hand-rolled charts.
export function computeDurationLayout(
  durationByType: DurationDatum[],
  width = 640,
  height = 200,
): DurationLayout {
  const marginLeft = 16
  const marginRight = 16
  const marginTop = 24
  const marginBottom = 32
  const plotWidth = width - marginLeft - marginRight
  const plotHeight = height - marginTop - marginBottom

  const maxMinutes = Math.max(...durationByType.map((d) => d.total_minutes), 1)
  const bandWidth = plotWidth / durationByType.length
  const barWidth = Math.min(24, bandWidth * 0.5)
  const baselineY = marginTop + plotHeight

  const bars: LayoutBar[] = durationByType.map((d, i) => {
    const bandCenter = marginLeft + bandWidth * (i + 0.5)
    const barHeight = Math.max((d.total_minutes / maxMinutes) * plotHeight, 2)
    const barTop = baselineY - barHeight
    const color = ACTIVITY_COLORS[d.activity_type] || CHART_INK.muted
    const r = Math.min(4, barHeight / 2)
    return {
      ...d,
      bandCenter,
      bandWidth,
      barHeight,
      barTop,
      color,
      r,
      left: bandCenter - barWidth / 2,
      right: bandCenter + barWidth / 2,
    }
  })

  return { width, height, marginLeft, marginRight, baselineY, bars }
}

export default function DurationChart({ durationByType }: { durationByType: DurationDatum[] }) {
  const [hovered, setHovered] = useState<number | null>(null)

  if (durationByType.length === 0) {
    return (
      <p className="text-sm italic text-text-muted">
        Not enough data yet — log some entries with a duration to see this chart.
      </p>
    )
  }

  const { width, height, marginLeft, marginRight, baselineY, bars } = computeDurationLayout(durationByType)
  const hoveredBar = hovered !== null ? bars[hovered] : null

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        role="img"
        aria-label="Total time logged by activity type"
        className="w-full"
      >
        <line x1={marginLeft} x2={width - marginRight} y1={baselineY} y2={baselineY} stroke={CHART_INK.axis} strokeWidth={1} />

        {bars.map((bar, i) => (
          <g key={bar.activity_type}>
            <path
              d={`M ${bar.left} ${baselineY} V ${bar.barTop + bar.r} Q ${bar.left} ${bar.barTop} ${bar.left + bar.r} ${bar.barTop} H ${bar.right - bar.r} Q ${bar.right} ${bar.barTop} ${bar.right} ${bar.barTop + bar.r} V ${baselineY} Z`}
              fill={bar.color}
              opacity={hovered === i ? 0.75 : 1}
            />
            <text x={bar.bandCenter} y={bar.barTop - 6} textAnchor="middle" fontSize={10} fill={CHART_INK.muted}>
              {formatMinutes(bar.total_minutes)}
            </text>
            <text x={bar.bandCenter} y={height - 10} textAnchor="middle" fontSize={10} fill={CHART_INK.muted}>
              {bar.activity_type}
            </text>
            <rect
              x={bar.bandCenter - bar.bandWidth / 2}
              y={24}
              width={bar.bandWidth}
              height={height - 24 - 32}
              fill="transparent"
              className="cursor-pointer"
              onPointerEnter={() => setHovered(i)}
              onPointerLeave={() => setHovered(null)}
            />
          </g>
        ))}
      </svg>

      {hoveredBar && (
        <div
          className="pointer-events-none absolute -translate-x-1/2 -translate-y-full rounded border border-border bg-card px-2 py-1 text-xs shadow-lg"
          style={{
            left: `${(hoveredBar.bandCenter / width) * 100}%`,
            top: `${(hoveredBar.barTop / height) * 100}%`,
          }}
        >
          <div className="font-semibold text-text-primary">{formatMinutes(hoveredBar.total_minutes)}</div>
          <div className="text-text-muted">
            {hoveredBar.activity_type} · {hoveredBar.entry_count} {hoveredBar.entry_count === 1 ? 'entry' : 'entries'}
          </div>
        </div>
      )}
    </div>
  )
}
