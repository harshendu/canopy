import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import type { BurndownResponse } from "../api/types";

export default function BurndownChart({ data }: { data: BurndownResponse }) {
  if (data.points.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        No completion history yet — burndown is driven by task status transitions synced from Jira.
      </p>
    );
  }
  const chartData = data.points.map((p) => ({
    week: p.week.slice(5),
    remaining: p.remaining,
    completed: p.completed,
  }));
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <ResponsiveContainer width="100%" height={300}>
        <LineChart data={chartData}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f1f5f9" />
          <XAxis dataKey="week" fontSize={12} />
          <YAxis allowDecimals={false} fontSize={12} />
          <Tooltip />
          <Legend />
          <Line type="monotone" dataKey="remaining" stroke="#dc2626" strokeWidth={2} dot={false} />
          <Line type="monotone" dataKey="completed" stroke="#2f855a" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
