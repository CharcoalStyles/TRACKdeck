import { describe, expect, it } from 'vitest'
import { computeMoodLayout } from './MoodChart'
import { computeDurationLayout } from './DurationChart'

describe('computeMoodLayout', () => {
  it('maps mood 1-10 to the plot\'s vertical extent, inverted (higher mood = higher on screen)', () => {
    const { points, marginLeft: _ml, height } = computeMoodLayout(
      [
        { date: '2026-01-01', avg_mood: 1, count: 1 },
        { date: '2026-01-02', avg_mood: 10, count: 1 },
      ],
      640,
      220,
    )
    const marginTop = 16
    const marginBottom = 28
    expect(points[0].y).toBeCloseTo(height - marginBottom, 5) // mood 1 -> bottom
    expect(points[1].y).toBeCloseTo(marginTop, 5) // mood 10 -> top
  })

  it('places a single day at the left margin (min span clamps to one day)', () => {
    const { points, marginLeft } = computeMoodLayout([{ date: '2026-01-01', avg_mood: 5, count: 1 }])
    expect(points[0].x).toBe(marginLeft)
  })

  it('breaks the line into segments where consecutive entries skip a calendar day', () => {
    const { segments } = computeMoodLayout([
      { date: '2026-01-01', avg_mood: 5, count: 1 },
      { date: '2026-01-02', avg_mood: 6, count: 1 },
      { date: '2026-01-05', avg_mood: 4, count: 1 }, // gap: gets its own segment
    ])
    expect(segments).toHaveLength(2)
    expect(segments[0]).toHaveLength(2)
    expect(segments[1]).toHaveLength(1)
  })

  it('produces y-axis ticks at mood values 1, 5, and 10', () => {
    const { yTicks } = computeMoodLayout([{ date: '2026-01-01', avg_mood: 5, count: 1 }])
    expect(yTicks.map((t) => t.value)).toEqual([1, 5, 10])
  })
})

describe('computeDurationLayout', () => {
  it('scales the tallest bar to the full plot height and others proportionally', () => {
    const { bars, baselineY } = computeDurationLayout(
      [
        { activity_type: 'Meal', total_minutes: 30, entry_count: 1 },
        { activity_type: 'Exercise', total_minutes: 60, entry_count: 1 },
      ],
      640,
      200,
    )
    const plotHeight = 200 - 24 - 32
    expect(bars[1].barHeight).toBeCloseTo(plotHeight, 5) // the max -> full plot height
    expect(bars[0].barHeight).toBeCloseTo(plotHeight / 2, 5) // half the max -> half height
    expect(bars[1].barTop).toBeCloseTo(baselineY - plotHeight, 5)
  })

  it('gives every bar a minimum visible height even for a tiny value', () => {
    const { bars } = computeDurationLayout([
      { activity_type: 'Meal', total_minutes: 500, entry_count: 1 },
      { activity_type: 'Rest', total_minutes: 1, entry_count: 1 },
    ])
    expect(bars[1].barHeight).toBeGreaterThanOrEqual(2)
  })

  it('assigns the fixed categorical color for a known activity type, and the muted fallback for an unknown one', () => {
    const { bars } = computeDurationLayout([
      { activity_type: 'Meal', total_minutes: 30, entry_count: 1 },
      { activity_type: 'Some New Type', total_minutes: 30, entry_count: 1 },
    ])
    expect(bars[0].color).toBe('#3987e5')
    expect(bars[1].color).toBe('#888')
  })

  it('spaces bands evenly across the plot width', () => {
    const { bars, marginLeft, width, marginRight } = computeDurationLayout([
      { activity_type: 'A', total_minutes: 10, entry_count: 1 },
      { activity_type: 'B', total_minutes: 10, entry_count: 1 },
    ])
    const plotWidth = width - marginLeft - marginRight
    expect(bars[0].bandCenter).toBeCloseTo(marginLeft + plotWidth * 0.25, 5)
    expect(bars[1].bandCenter).toBeCloseTo(marginLeft + plotWidth * 0.75, 5)
  })
})
