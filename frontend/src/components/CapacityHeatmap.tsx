import type { CapacityResponse } from "../api/types";

function cellColor(pct: number): string {
  if (pct <= 0) return "transparent";
  if (pct > 100) return "rgba(220,38,38,0.85)"; // over-allocated
  const alpha = 0.15 + (pct / 100) * 0.7;
  return `rgba(47,133,90,${alpha.toFixed(2)})`; // canopy green scale
}

export default function CapacityHeatmap({ data }: { data: CapacityResponse }) {
  if (data.rows.length === 0) {
    return (
      <p className="text-sm text-slate-500">
        No allocations yet — assign engineers to this project to see capacity.
      </p>
    );
  }
  return (
    <div className="overflow-auto rounded-lg border border-slate-200 bg-white">
      <table className="text-xs">
        <thead>
          <tr>
            <th className="sticky left-0 bg-white px-3 py-2 text-left font-medium text-slate-500">
              Engineer
            </th>
            {data.weeks.map((w) => (
              <th key={w} className="px-2 py-2 font-normal text-slate-400">
                {w.slice(5)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.map((row) => (
            <tr key={row.engineer_id}>
              <td className="sticky left-0 bg-white px-3 py-2 font-medium">
                {row.engineer_name}
              </td>
              {data.weeks.map((w) => {
                const pct = row.cells[w] ?? 0;
                return (
                  <td
                    key={w}
                    className="px-2 py-2 text-center text-slate-700"
                    style={{ backgroundColor: cellColor(pct) }}
                    title={`${row.engineer_name} · ${w}: ${pct}%`}
                  >
                    {pct ? `${pct}%` : ""}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
