// SVG chart libraries (recharts) can't read CSS custom properties, so chart
// marks need literal hex values. This hook mirrors the light/dark hex pairs
// already defined in styles/tokens.css (--color-accent/--color-success/
// --color-warning) rather than inventing a new palette, and reacts to
// ThemeToggle's `data-theme` attribute so charts repaint on toggle.

import { useEffect, useState } from 'react'

function readTheme(): 'light' | 'dark' {
  return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark'
}

const PALETTE = {
  light: {
    accent: '#0C66E4',
    success: '#216E4E',
    warning: '#974F0C',
    grid: '#dfe1e6',
    axis: '#5e6c84',
  },
  dark: {
    accent: '#6ea8fe',
    success: '#4cae6a',
    warning: '#d6a94e',
    grid: '#3a3a3a',
    axis: '#b4b4b4',
  },
} as const

export type ChartColors = {
  accent: string
  success: string
  warning: string
  grid: string
  axis: string
}

export function useChartColors(): ChartColors {
  const [theme, setTheme] = useState<'light' | 'dark'>(readTheme)

  useEffect(() => {
    const target = document.documentElement
    const observer = new MutationObserver(() => setTheme(readTheme()))
    observer.observe(target, { attributes: true, attributeFilter: ['data-theme'] })
    return () => observer.disconnect()
  }, [])

  return PALETTE[theme]
}
