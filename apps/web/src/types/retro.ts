// apps/web/src/types/retro.ts

export interface ActionItem { action: string; owner: string | null; priority: 'high' | 'medium' | 'low'; }
export interface RetroPattern {
  id: string; patternType: string; description: string; occurrenceCount: number;
  firstSeenAt: string | null; lastSeenAt: string | null;
  status: 'active' | 'resolved'; affectedSprintNames: string[];
}
export interface RetroResponse {
  retroId: string; sprintId: string; sprintName: string; generatedAt: string;
  wentWell: string[]; wentPoorly: string[]; actionItems: ActionItem[];
  patterns: RetroPattern[];
  velocitySummary: { committed: number; delivered: number; completionRate: number; };
}
