type JsonValue = string | number | boolean | null | JsonRecord | JsonValue[];
type JsonRecord = Record<string, any>;

interface StatusResponse extends JsonRecord {
  version: string;
  workspace?: {
    id?: string;
    name?: string;
    kind?: string;
    isSandbox?: boolean;
    currentWorkspaceId?: string;
    snapshotRoot?: string | null;
  };
  snapshotRoot: string | null;
  databasePath: string;
  appDataPath: string;
  careerCount: number;
  snapshotCount: number;
  failedImportCount: number;
  readyCount: number;
  watcherActive: boolean;
  lastScanAt: string | null;
  lastImportAt: string | null;
  matchStats?: {
    model?: string;
    exports?: number;
    linked?: number;
    pending?: number;
    pairedCaptures?: number;
    lastImportAt?: string | null;
    lastScanAt?: string | null;
    roots?: string[];
  };
}


interface CareerClock extends JsonRecord {
  careerDate: string | null;
  source: "transfer_pulse" | "snapshot" | null;
  snapshotDate: string | null;
  pulseDate?: string | null;
  stalenessDays?: number;
  seasonIndex?: number | null;
  managedTeamId?: number | null;
  snapshotId?: number | null;
  pulseId?: number | null;
  pulseCount?: number;
  recentPulses?: JsonRecord[];
}

interface CareerSummary extends JsonRecord {
  id: number;
  display_name: string;
  initial_team_name?: string | null;
  manager_name?: string | null;
}

interface SnapshotSummary extends JsonRecord {
  id: number;
  career_id: number;
  career_date: string;
  season_index: number;
  import_sequence: number;
  same_day_sequence: number;
  managed_team_name?: string | null;
  exporter_version?: string | null;
  season_start_year?: number | null;
  season_label?: string | null;
  career_season_number?: number | null;
  ea_season_index?: number | null;
}

interface SearchResult extends JsonRecord {
  type: "player" | "club" | "competition";
  id: number;
  label: string;
  subtitle?: string;
  extra?: string;
  meta?: number;
}

interface MediaProgressResponse extends JsonRecord {
  active: boolean;
  phase: string;
  queue?: number;
  processing?: JsonRecord;
}

interface AtlasState {
  status: StatusResponse | null;
  careers: CareerSummary[];
  snapshots: SnapshotSummary[];
  careerClock: CareerClock | null;
  careerId: number | null;
  snapshotId: number | null;
  route: string;
  routeData: JsonRecord;
  history: Array<{route: string; data: JsonRecord}>;
  historyIndex: number;
  searchResults: SearchResult[];
  searchIndex: number;
  playerTab: string;
  playerComparisonScope: "club" | "league";
  playerComparisonMode: "group" | "position";
  squadQuery: string;
  squadPosition: string;
  squadSort: string;
  competitionQuery: string;
  matchCompetition: string;
  compareFrom: number | null;
  compareTo: number | null;
  competitionTab: string;
  chronologyType: string;
  chronologyQuery: string;
  loanScope: string;
  transferScope: string;
  movementSeasonIndex: number | null;
  movementEditKind: "transfer" | "loan" | null;
  movementEditId: number | null;
  analysisSeasonIndex: number | null;
  recordsSeasonIndex: number | null;
  seasonReportSeasonIndex: number | null;
  seasonReportTab: string;
  analysisTab: string;
  clubTab: string;
  competitionListTab: string;
  mediaType: string;
  mediaStatus: string;
  mediaSources: JsonRecord[] | null;
  manualSeasonId: number | null;
  manualTab: string;
  manualEditKind: string | null;
  manualEditId: number | null;
  manualDraftCompetitionId: number | null;
  manualQuickEntry: boolean;
  pendingLiveRender: boolean;
  llmProvider: string;
  llmKeys: Record<string, string>;
}

interface TableHeader { label: string; cls?: string; sortable?: boolean; }
interface SortValue { type: "text" | "number" | "empty"; value: string | number | null; }

interface ManualSeason extends JsonRecord {
  id: number;
  career_id: number;
  season_index: number;
  label: string;
  start_year?: number | null;
  end_year?: number | null;
  managed_team_ea_id?: number | null;
  managed_team_name?: string | null;
  notes?: string | null;
  competition_count?: number;
  stat_count?: number;
  transaction_count?: number;
}

interface ManualCompetition extends JsonRecord {
  id: number;
  manual_season_id: number;
  competition_type: string;
  competition_object_id?: number | null;
  static_competition_id?: number | null;
  competition_name: string;
  final_position?: number | null;
  result_text?: string | null;
  notes?: string | null;
}

interface ManualPlayerStat extends JsonRecord {
  id: number;
  manual_competition_id: number;
  manual_season_id: number;
  player_ea_id?: number | null;
  display_name: string;
  appearances: number;
  goals: number;
  assists: number;
  clean_sheets: number;
  average_rating?: number | null;
  competition_name: string;
  notes?: string | null;
  updated_at?: string | null;
}

interface ManualLeagueFinish extends JsonRecord {
  id: number;
  manual_season_id: number;
  team_ea_id?: number | null;
  team_name: string;
  league_ea_id?: number | null;
  league_name: string;
  final_position: number;
  notes?: string | null;
  updated_at?: string | null;
}

interface ManualTransaction extends JsonRecord {
  id: number;
  manual_season_id: number;
  transaction_type: "transfer" | "loan";
  direction: "incoming" | "outgoing";
  player_ea_id?: number | null;
  display_name: string;
  from_team_name?: string | null;
  to_team_name?: string | null;
  fee?: number | null;
  currency?: string;
  transaction_date?: string | null;
  loan_end_date?: string | null;
  updated_at?: string | null;
}

interface ManualDataResponse extends JsonRecord {
  career: CareerSummary;
  seasons: ManualSeason[];
  competitions: ManualCompetition[];
  stats: ManualPlayerStat[];
  transactions: ManualTransaction[];
  leagueFinishes: ManualLeagueFinish[];
  developments?: JsonRecord[];
  changes: JsonRecord[];
  backups: JsonRecord[];
  references: {
    players: JsonRecord[];
    teams: JsonRecord[];
    competitions: JsonRecord[];
    leagues: JsonRecord[];
  };
}
