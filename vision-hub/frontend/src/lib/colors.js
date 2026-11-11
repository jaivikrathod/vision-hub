// Colour roles. Labels map to FIXED categorical slots (colour follows the entity, never
// its rank), so "walking" is the same colour in every chart, timeline and overlay.
// Palette: the validated reference categorical palette (light and dark steps).

const SLOTS = {
  light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'],
  dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#008300', '#9085e9', '#e66767'],
}
const NEUTRAL = { light: '#9ca3af', dark: '#6b7280' }

// Activities and postures share slots so "standing" means the same colour everywhere.
const LABEL_SLOT = {
  walking: 0,
  running: 1,
  jumping: 2,
  standing: 3,
  sitting: 4,
  'lying down': 5,
  bending: 6,
  falling: 7,
}

export const KNOWN_LABELS = Object.keys(LABEL_SLOT)

export function isDark() {
  return typeof document !== 'undefined' && document.documentElement.classList.contains('dark')
}

/** Colour for an activity/posture label. Unknown, uncertain and custom labels are neutral grey. */
export function labelColor(label, dark = isDark()) {
  const slot = LABEL_SLOT[label]
  return slot === undefined ? NEUTRAL[dark ? 'dark' : 'light'] : SLOTS[dark ? 'dark' : 'light'][slot]
}

/** Stable, distinct colour per tracked person (same formula as the backend annotator). */
export function trackColor(trackId) {
  if (trackId == null) return '#22c55e'
  const hue = ((trackId * 0.618033988749895) % 1) * 360
  return `hsl(${hue.toFixed(0)} 75% 55%)`
}

export const SERIES_COLOR = { light: '#2a78d6', dark: '#3987e5' }
