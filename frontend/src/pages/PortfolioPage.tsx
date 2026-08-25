import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { usePortfolio, usePortfolioHistory } from "../lib/queries";
import { formatMoney, parseMoney } from "../lib/types";

export default function PortfolioPage() {
  const { data: summary, isLoading: summaryLoading } = usePortfolio();
  const { data: history, isLoading: historyLoading } = usePortfolioHistory();

  if (summaryLoading || historyLoading) {
    return <p className="p-6 text-neutral-500">Loading...</p>;
  }
  if (!summary) return <p className="p-6 text-neutral-500">No portfolio data yet.</p>;

  const gain = parseMoney(summary.unrealized_gain) ?? 0;
  const chartData = (history ?? []).map((p) => ({
    date: p.observed_on,
    value: parseMoney(p.total_market_value) ?? 0,
  }));

  return (
    <div className="mx-auto max-w-4xl p-6">
      <h1 className="mb-4 text-xl font-semibold">Portfolio</h1>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <StatCard label="Market value" value={formatMoney(summary.total_market_value)} />
        <StatCard label="Cost basis" value={formatMoney(summary.total_cost_basis)} />
        <StatCard
          label="Unrealized gain"
          value={formatMoney(summary.unrealized_gain)}
          tone={gain > 0 ? "positive" : gain < 0 ? "negative" : "neutral"}
        />
      </div>

      <p className="mt-3 text-xs text-neutral-400">
        {summary.priced_item_count} / {summary.item_count} holdings priced
        {summary.price_date ? ` · prices as of ${summary.price_date}` : ""}
      </p>

      <div className="mt-8 rounded-lg border border-neutral-200 bg-white p-4">
        <h2 className="mb-3 text-sm font-medium text-neutral-700">Value over time</h2>
        {chartData.length < 2 ? (
          <p className="py-12 text-center text-sm text-neutral-400">
            Not enough price history yet -- this fills in as daily price snapshots accumulate.
          </p>
        ) : (
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis
                  tick={{ fontSize: 11 }}
                  tickFormatter={(v: number) => `$${v.toFixed(0)}`}
                  width={56}
                />
                <Tooltip formatter={(v: number) => [`$${v.toFixed(2)}`, "Value"]} />
                <Line
                  type="monotone"
                  dataKey="value"
                  stroke="#059669"
                  strokeWidth={2}
                  dot={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "positive" | "negative" | "neutral";
}) {
  const toneClass =
    tone === "positive"
      ? "text-emerald-600"
      : tone === "negative"
        ? "text-red-600"
        : "text-neutral-900";
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-4">
      <div className="text-xs text-neutral-500">{label}</div>
      <div className={`mt-1 text-2xl font-semibold ${toneClass}`}>{value}</div>
    </div>
  );
}
