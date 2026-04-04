export type DependencyType = 'blocks' | 'is_blocked_by' | 'external_service' | 'cross_team';
export type RiskLevel = 'high' | 'medium' | 'low';

export interface DependencyItem {
  id: string;
  ticketKey: string;
  ticketTitle: string;
  blockedByKey: string | null;
  dependencyType: DependencyType;
  riskLevel: RiskLevel;
  description: string | null;
  source: 'jira' | 'manual';
  resolvedAt: string | null;
  createdAt: string;
}

export interface RadarResponse {
  teamId: string;
  riskScore: number;
  dependencies: DependencyItem[];
}

export interface ScanResponse {
  scannedAt: string;
  dependenciesFound: number;
  riskScore: number;
}
