export interface TicketAnalysisResult {
  ticketKey: string; ticketTitle: string; readinessScore: number;
  status: 'ready' | 'needs_work' | 'blocked'; issues: string[]; suggestions: string[];
  stackAlignment: number | null;
  matchedIdentifierCount: number | null;
  suggestedRevision: import('./inlineRefinement').SuggestedRevision | null;
  fetchedUpdatedAt: string | null;
}
export interface ScopeCopSummary {
  totalTickets: number; readyCount: number; needsWorkCount: number; blockedCount: number;
}
export interface AnalyzeResponse {
  analyzedAt: string; results: TicketAnalysisResult[]; summary: ScopeCopSummary;
}
