import { useMemo } from 'react'
import { CalendarDays, Columns3, List, Rows3 } from 'lucide-react'
import type { SegmentedOption } from '../ui/SegmentedControl'
import { useFeature } from '../../featureFlags'

/** The four ways the planner can lay out the same task data. */
export type PlannerView = 'week' | 'day' | 'list' | 'board'

/**
 * Shared by the top bar (which owns the switcher) and the toolbar (which reads
 * `view` to decide whether to show the date nav). Keeping the option list in
 * one place stops the two from drifting.
 */
export const VIEW_OPTIONS: readonly SegmentedOption<PlannerView>[] = [
  { value: 'week', label: 'Week view', icon: <CalendarDays size={14} /> },
  { value: 'day', label: 'Day view', icon: <Rows3 size={14} /> },
  { value: 'list', label: 'List view', icon: <List size={14} /> },
  { value: 'board', label: 'Board view', icon: <Columns3 size={14} /> },
]

/**
 * The subset of VIEW_OPTIONS actually available given current feature flags.
 * 'day' (DayAgenda, the "Up next" queue) is never gated — it's the permanent
 * fallback every other view degrades to when its own flag is off. Shared by
 * TopBar (filters the switcher) and DashboardLayout (validates/corrects the
 * active view) so neither duplicates the useFeature calls or the filter.
 */
export function usePlannerViewOptions(): readonly SegmentedOption<PlannerView>[] {
  const weekEnabled = useFeature('planner.week_view')
  const listEnabled = useFeature('planner.daily_calendar_view')
  const boardEnabled = useFeature('planner.board_view')
  return useMemo(
    () =>
      VIEW_OPTIONS.filter(o => {
        if (o.value === 'week') return weekEnabled
        if (o.value === 'list') return listEnabled
        if (o.value === 'board') return boardEnabled
        return true // 'day' — always available
      }),
    [weekEnabled, listEnabled, boardEnabled],
  )
}

/** Shape shared from DashboardLayout to PlannerPage via React Router's Outlet. */
export interface PlannerOutletContext {
  view: PlannerView
  setView: (view: PlannerView) => void
  /** People-panel collapse state — owned by the layout so the top-bar toggle
   *  (its industry-standard spot) and the planner share one value. */
  lanesHidden: boolean
  onToggleLanes: () => void
}
