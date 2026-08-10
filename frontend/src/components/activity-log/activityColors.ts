// Fixed entity->color mapping (dataviz skill's validated dark categorical
// slots 1/2/3/4/5 — passes CVD/contrast checks against this app's card
// surface). Color always follows the activity type, never its position
// in a given result set.
export const ACTIVITY_COLORS: Record<string, string> = {
  Meal: '#3987e5',
  Exercise: '#d95926',
  'Project Work': '#199e70',
  Socializing: '#c98500',
  Rest: '#d55181',
}

export const CHART_INK = { muted: '#888', grid: '#2a2a2a', axis: '#444' }

export function formatMinutes(totalMinutes: number): string {
  if (totalMinutes < 60) return `${totalMinutes}m`
  const hours = Math.floor(totalMinutes / 60)
  const mins = totalMinutes % 60
  return mins === 0 ? `${hours}h` : `${hours}h ${mins}m`
}

export function formatDay(dateStr: string): string {
  return new Date(`${dateStr}T00:00:00`).toLocaleDateString([], { month: 'short', day: 'numeric' })
}
