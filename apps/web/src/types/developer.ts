export interface DeveloperProfileResponse {
  developerId: string; name: string; role: string | null;
  avgVelocity: number; sprintCount: number;
  strongTicketTypes: string[]; domains: string[]; consistencyScore: number;
}
