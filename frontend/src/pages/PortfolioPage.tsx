import { useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useHoldings, usePortfolio, usePortfolioHistory } from "../lib/queries";
import type { HoldingGroupKey } from "../lib/types";
import { DEFAULT_GROUP_KEYS, formatMoney, parseMoney } from "../lib/types";
import HoldingsPanel from "../components/HoldingsPanel";
import { tooltipStyles, useChartColors } from "../lib/chartTheme";
import {
  ErrorState,
  LoadingState,
  Page,
  PageHeader,
  Panel,
  SectionLabel,
  Stat,
} from "../components/ui";

export default function PortfolioPage() {
  const { data: summary, isLoading: summaryLoading } = usePortfolio();
  const { data: history, isLoading: historyLoading } = usePortfolioHistory();
  const [groupBy, setGroupBy] = useState<HoldingGroupKey[]>(DEFAULT_GROUP_KEYS);
  const { data: holdings, isLoading: holdingsLoading } = useHoldings(groupBy);

  if (summaryLoading || historyLoading) return <LoadingState />;
  if (!summary) return <ErrorState message="No portfolio data yet." />;

  const gain = parseMoney(summary.unrealized_gain) ?? 0;
  const chartData = (history ?? []).map((p) => ({
    date: p.observed_on,
    value: parseMoney(p.total_market_value) ?? 0,
  }));

  return (
    <Page width="narrow">
      <PageHeader
        title="Portfolio"
        subtitle={
          <>
            {summary.priced_item_count} / {summary.item_count} holdings priced
            {summary.price_date ? ` · prices as of ${summary.price_date}` : ""}
          </>
        }
      />

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Stat label="Market value" value={formatMoney(summary.total_market_value)} />
        <Stat label="Cost basis" value={formatMoney(summary.total_cost_basis)} />
        <Stat
          label="Unrealized gain"
          value={formatMoney(summary.unrealized_gain)}
          tone={gain > 0 ? "positive" : gain < 0 ? "negative" : "neutral"}
        />
      </div>

      <Panel className="mt-6 p-4">
        <SectionLabel className="mb-4">Value over time</SectionLabel>
        {chartData.length < 2 ? (
          <p className="py-14 text-center text-[12.5px] text-ink-3">
            Not enough price history yet — this fills in as daily price snapshots accumulate.
          </p>
        ) : (
          <ValueChart data={chartData} />
        )}
      </Panel>

      <Panel className="mt-6 p-4">
        <SectionLabel className="mb-4">Holdings</SectionLabel>
        {holdingsLoading ? (
          <p className="py-10 text-center font-mono text-[12px] uppercase tracking-[0.08em] text-ink-3">
            Loading holdings
          </p>
        ) : (
          <HoldingsPanel holdings={holdings ?? []} groupBy={groupBy} onGroupByChange={setGroupBy} />
        )}
      </Panel>
    </Page>
  );
}

function ValueChart({ data }: { data: { date: string; value: number }[] }) {
  const c = useChartColors();
  const t = tooltipStyles(c);

  return (
    <div className="h-64">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={c.grid} vertical={false} />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11, fill: c.axis }}
            stroke={c.grid}
            tickLine={false}
          />
          <YAxis
            tick={{ fontSize: 11, fill: c.axis }}
            stroke={c.grid}
            tickLine={false}
            tickFormatter={(v: number) => `$${v.toFixed(0)}`}
            width={56}
          />
          <Tooltip
            formatter={(v: number) => [`$${v.toFixed(2)}`, "Value"]}
            contentStyle={t.contentStyle}
            labelStyle={t.labelStyle}
            itemStyle={t.itemStyle}
          />
          <Line type="monotone" dataKey="value" stroke={c.accent} strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
