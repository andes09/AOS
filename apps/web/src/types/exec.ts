export type RAGStatus = 'green' | 'amber' | 'red';
export type VelocityTrend = 'accelerating' | 'stable' | 'declining';

export interface TeamSummary {
  teamId: string;
  name: string;
  healthScore: number;
  status: RAGStatus;
  velocityTrend: VelocityTrend;
  sprintCompletionRate: number;
  lastSprintName: string | null;
  hasActiveSprint: boolean;
}

export interface SectorOverviewResponse {
  orgId: string;
  sectorHealthScore: number;
  teamCount: number;
  teams: TeamSummary[];
}

export interface PlanQualityPoint {
  sprintId: string;
  sprintName: string;
  completedAt: string | null;
  overrideRate: number | null;
  overridesByReason: Record<string, number> | null;
}

export interface RevisionAcceptancePoint {
  sprintId: string;
  sprintName: string;
  completedAt: string | null;
  proposed: number;
  acceptedVerbatim: number;
  edited: number;
  acceptanceRate: number;
}
