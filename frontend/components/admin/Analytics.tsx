"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { fmtElapsed } from "@/lib/format";

interface Stats {
  quiz_whiz: { team: string; correct: number } | null;
  fastest_solver: { team: string; elapsed_ms: number } | null;
  most_accurate: { team: string; pass_rate: number; submissions: number } | null;
  best_golfer: { team: string; chars: number } | null;
  most_efficient: { team: string; top_ms: number; class: string | null } | null;
  questions: {
    question_id: string;
    round_name: string;
    title: string;
    type: string;
    submissions?: number;
    runs?: number;
    teams_submitting?: number;
    attempts_per_team?: number;
    teams_passing?: number;
    avg_time_to_first_pass_ms?: number | null;
    answers?: number;
    correct_rate?: number | null;
    avg_answer_ms?: number | null;
  }[];
}

export function Analytics({ gameId, refreshKey }: { gameId: string; refreshKey: string }) {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api<Stats>(`/games/${gameId}/analytics`)
      .then(setStats)
      .catch(() => setError("Couldn't load stats"));
  }, [gameId, refreshKey]);

  const award = (label: string, v: string | null) => (
    <div className="rounded-md bg-ink-700 p-3">
      <div className="text-xs text-ink-400">{label}</div>
      <div className="font-bold text-white">{v ?? "–"}</div>
    </div>
  );

  return (
    <div className="space-y-3 rounded-lg bg-ink-800 p-4 ring-1 ring-ink-600">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="font-bold text-white">Stats</h3>
        <div className="flex gap-2">
          <a href={`/api/games/${gameId}/analytics.csv?kind=teams`} className="rounded-md bg-ink-600 px-2.5 py-1 text-xs font-semibold text-ink-200 hover:bg-ink-500">
            CSV: teams
          </a>
          <a href={`/api/games/${gameId}/analytics.csv?kind=submissions`} className="rounded-md bg-ink-600 px-2.5 py-1 text-xs font-semibold text-ink-200 hover:bg-ink-500">
            CSV: submissions
          </a>
        </div>
      </div>
      {error && <p className="text-sm text-fail">{error}</p>}
      {stats && (
        <>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-5">
            {award("Quiz whiz", stats.quiz_whiz && `${stats.quiz_whiz.team} (${stats.quiz_whiz.correct} right)`)}
            {award("Fastest solver", stats.fastest_solver && `${stats.fastest_solver.team} (${fmtElapsed(stats.fastest_solver.elapsed_ms)})`)}
            {award("Most accurate", stats.most_accurate && `${stats.most_accurate.team} (${Math.round(stats.most_accurate.pass_rate * 100)}%)`)}
            {award("Best golfer", stats.best_golfer && `${stats.best_golfer.team} (${stats.best_golfer.chars} chars)`)}
            {award("Most efficient", stats.most_efficient && `${stats.most_efficient.team} (${Math.round(stats.most_efficient.top_ms)} ms)`)}
          </div>
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-ink-400">
              <tr>
                <th className="py-1">Round</th>
                <th>Answers / submissions</th>
                <th>Correct / passing</th>
                <th>Avg time</th>
              </tr>
            </thead>
            <tbody>
              {stats.questions.map((q) => (
                <tr key={q.question_id} className="border-t border-ink-700">
                  <td className="py-1 text-white">{q.round_name}</td>
                  {q.type === "multiple_choice" ? (
                    <>
                      <td className="font-mono">{q.answers}</td>
                      <td className="font-mono">{q.correct_rate != null ? `${Math.round(q.correct_rate * 100)}%` : "–"}</td>
                      <td className="font-mono">{q.avg_answer_ms != null ? `${(q.avg_answer_ms / 1000).toFixed(1)} s` : "–"}</td>
                    </>
                  ) : (
                    <>
                      <td className="font-mono">
                        {q.submissions} <span className="text-ink-400">({q.runs} runs)</span>
                      </td>
                      <td className="font-mono">{q.teams_passing} teams</td>
                      <td className="font-mono">{q.avg_time_to_first_pass_ms != null ? fmtElapsed(q.avg_time_to_first_pass_ms) : "–"}</td>
                    </>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
    </div>
  );
}
