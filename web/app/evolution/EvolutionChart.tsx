"use client";

import {
  CartesianGrid,
  Label,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";

export type Point = {
  family: string;
  date: number;
  dateLabel: string;
  score: number;
  vram: number | null;
  clean?: number;        // # challenges published after release (the held-out sample size)
};

export default function EvolutionChart({ points }: { points: Point[] }) {
  return (
    <ResponsiveContainer width="100%" height={420}>
      <ScatterChart margin={{ top: 16, right: 24, bottom: 32, left: 8 }}>
        <CartesianGrid stroke="#292524" />
        <XAxis
          type="number"
          dataKey="date"
          domain={["dataMin", "dataMax"]}
          tickFormatter={(t) => new Date(t).toISOString().slice(0, 7)}
          stroke="#78716c"
          tick={{ fontSize: 12 }}
        >
          <Label value="model release date" offset={-20} position="insideBottom" fill="#78716c" />
        </XAxis>
        <YAxis
          type="number"
          dataKey="score"
          domain={[0, 1]}
          stroke="#78716c"
          tick={{ fontSize: 12 }}
        >
          <Label value="held-out code score" angle={-90} position="insideLeft" fill="#78716c" />
        </YAxis>
        <ZAxis range={[80, 80]} />
        <Tooltip
          cursor={{ stroke: "#44403c" }}
          contentStyle={{ background: "#1c1917", border: "1px solid #44403c", borderRadius: 8 }}
          labelStyle={{ color: "#e7e5e4" }}
          formatter={(_v, _n, p) => {
            const d = p.payload as Point;
            const n = d.clean != null ? ` · ${d.clean} held-out challenges` : "";
            return [`${d.family} — ${d.score.toFixed(3)}${n} (released ${d.dateLabel})`, ""];
          }}
        />
        <Scatter data={points} fill="#10b981" />
      </ScatterChart>
    </ResponsiveContainer>
  );
}
