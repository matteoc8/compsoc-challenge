// Shapes of the WebSocket messages and snapshots. The backend publishes the same shapes in
// OpenAPI (`npm run gen:types` writes lib/api-types.ts); these add the detail the UI uses.

export type Role = "team" | "teacher" | "screen";
export type GameStateName =
  | "lobby"
  | "round_intro"
  | "open"
  | "paused"
  | "closed"
  | "judging"
  | "results"
  | "leaderboard"
  | "podium"
  | "finished";
export type QType = "multiple_choice" | "super_fast" | "code_golf" | "best_complexity";

export interface GameHeader {
  id: string;
  state: GameStateName;
  question_index: number;
  question_count: number;
  round_name: string | null;
  question_type: QType | null;
  deadline: string | null;
  paused: boolean;
  remaining_ms: number | null;
  ending: boolean;
  ended_early: boolean;
  phase_ends_at: string | null;
  server_time: string;
  judge_ok: boolean;
  join_code?: string;
}

export interface BoardRow {
  team_id: string;
  name: string;
  points: number;
  rank: number;
  prev_rank?: number | null;
  prev_points?: number;
}

export interface IOCase {
  stdin: string;
  expected: string;
}

export interface PublicQuestion {
  id: string;
  position: number;
  round_name: string;
  type: QType;
  type_label: string;
  rule_line: string;
  title: string;
  description_md: string;
  image_url: string | null;
  image_alt: string | null;
  time_limit_s: number;
  scoring_max: number;
  starter_code?: string;
  examples?: IOCase[];
  tests_total?: number;
  cpu_limit_s?: number;
  memory_mb?: number;
  scoring?: Record<string, number | string | number[]>;
  golf_rule?: string;
  benchmark_sizes?: number[];
  options?: { index: number; text: string }[]; // multiple choice
  correct?: number[]; // teacher console only
}

export interface SubmissionResult {
  id: number;
  attempt: number;
  status: "queued" | "running" | "judged" | "error";
  passed: number | null;
  total: number | null;
  verdict: string | null;
  first_failed: number | null;
  error_summary: string | null;
  chars: number;
  elapsed_ms: number;
  time_ms: number | null;
  points: number | null;
  submitted_at: string;
  provisional?: boolean;
}

export interface RunCase {
  index: number;
  stdin: string | null;
  stdout: string;
  stderr: string;
  status: string;
  time_ms: number | null;
  memory_kb: number | null;
  expected?: string;
  passed?: boolean;
}

export interface RunResult {
  run_id: number;
  custom?: boolean;
  cases?: RunCase[];
  error?: string;
}

export interface MonitorRow {
  team_id: string;
  name: string;
  kicked: boolean;
  online: boolean;
  best_pass_rate?: number | null;
  best_chars?: number | null;
  first_full_ms?: number | null;
  passing?: boolean;
  in_flight?: boolean;
  provisional_points?: number | null;
  attempts?: number;
  runs?: number;
  // multiple choice
  answered?: boolean;
  choice?: number | null;
  correct?: boolean | null;
  answer_ms?: number | null;
}

export interface Progress {
  type: QType;
  teams_total: number;
  passing: number;
  solves?: { team_id: string; name: string; elapsed_ms: number }[];
  place_points?: number[]; // Super Fast: points for 1st, 2nd, 3rd…
  best_chars?: number | null;
  answered?: number; // multiple choice
}

export interface ResultRow {
  team_id: string;
  name: string;
  points: number;
  attempts?: number;
  passed?: number | null;
  total?: number | null;
  first_full_ms?: number | null;
  chars?: number | null;
  time_ms?: number | null;
  class_label?: string | null;
  timed_out?: boolean;
  wrong_at_scale?: boolean;
  choice?: number | null; // multiple choice
  correct?: boolean;
  answer_ms?: number | null;
}

export interface Results {
  question_id: string;
  type: QType;
  round_name: string;
  title: string;
  rows: ResultRow[];
  top3?: { team_id: string; name: string; chars: number; code: string }[];
  solves?: { team_id: string; name: string; elapsed_ms: number }[];
  sizes?: number[];
  floor_ms?: number;
  options?: { index: number; text: string; correct: boolean; count: number }[]; // multiple choice
  answered?: number;
}

export interface Adjustment {
  id: number;
  team_id: string;
  team: string;
  points: number;
  reason: "manual" | "undo";
  note: string | null;
  undone: boolean;
  created_at: string;
}

export interface Snapshot {
  role: Role;
  game: GameHeader;
  leaderboard: BoardRow[];
  intro?: { round_name: string; type: QType; type_label: string; rule_line: string; position: number; count: number; question_text?: string | null };
  question?: PublicQuestion;
  results?: Results | null;
  podium?: BoardRow[];
  teams?: { team_id: string; name: string; online: boolean }[];
  progress?: Progress;
  me?: { team_id: string; name: string; points: number; rank: number | null; teams_total: number };
  my_submissions?: SubmissionResult[];
  my_question_points?: number | null;
  my_answer?: { choice: number } | null;
  monitor?: MonitorRow[];
  in_flight?: number;
  screen_token?: string;
  questions?: { id: string; position: number; round_name: string; title: string; type: QType }[];
  adjustments?: Adjustment[];
  settings?: { allow_negative_totals?: boolean; show_reasons?: boolean; sounds?: boolean };
  all_teams?: { team_id: string; name: string; kicked: boolean }[];
}

export interface PointsAdjusted {
  team_id: string;
  team: string;
  delta: number;
  note: string | null;
  show_note: boolean;
  total: number;
}

export interface WsMessage {
  type: string;
  seq: number;
  data: any; // eslint-disable-line @typescript-eslint/no-explicit-any
}
