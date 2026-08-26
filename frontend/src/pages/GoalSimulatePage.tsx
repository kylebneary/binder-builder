import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useGoalDetail, useRunSimulation, useSealedProducts, useSets } from "../lib/queries";
import type {
  Objective,
  RankedStrategyOut,
  SealedProductOut,
  SimulateIn,
} from "../lib/types";
import { formatMoney } from "../lib/types";

const OBJECTIVES: { value: Objective; label: string }[] = [
  { value: "min_expected_cost", label: "Minimize expected cost" },
  { value: "min_p90_cost", label: "Minimize worst-case (p90) cost" },
];

function strategyLabel(strategy: RankedStrategyOut["strategy"], products: SealedProductOut[]): string {
  const entries = Object.entries(strategy.units);
  if (entries.length === 0) return "Singles only";
  return entries
    .map(([id, qty]) => {
      const name = products.find((p) => p.id === Number(id))?.name ?? `product ${id}`;
      return `${qty}x ${name}`;
    })
    .join(" + ");
}

export default function GoalSimulatePage() {
  const { goalId } = useParams<{ goalId: string }>();
  const id = goalId ? Number(goalId) : undefined;
  const { data: goal, isLoading: goalLoading } = useGoalDetail(id);
  const { data: sets } = useSets();
  const ptcgSetId = useMemo(
    () => sets?.find((s) => s.id === goal?.set_id)?.ptcg_set_id,
    [sets, goal],
  );
  const { data: sealedProducts, isLoading: productsLoading } = useSealedProducts(ptcgSetId);
  const runSimulation = useRunSimulation(id);

  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [objective, setObjective] = useState<Objective>("min_expected_cost");
  const [liquidationRate, setLiquidationRate] = useState(0.7);
  const [resaleFloor, setResaleFloor] = useState(2.0);

  function toggle(productId: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(productId)) next.delete(productId);
      else next.add(productId);
      return next;
    });
  }

  function runOptimizer() {
    const body: SimulateIn = {
      objective,
      liquidation_rate: liquidationRate,
      resale_floor: resaleFloor,
      sealed_product_ids: selectedIds.size > 0 ? Array.from(selectedIds) : undefined,
    };
    runSimulation.mutate(body);
  }

  if (goalLoading) return <p className="p-6 text-neutral-500">Loading...</p>;
  if (!goal) return <p className="p-6 text-neutral-500">Goal not found.</p>;

  const response = runSimulation.data;
  const baseline = response?.ranked.find((r) => Object.keys(r.strategy.units).length === 0);
  const best = response?.ranked[0];

  return (
    <div className="mx-auto max-w-4xl p-6">
      <div className="mb-4">
        <Link to={`/goals/${goal.id}`} className="text-sm text-neutral-500 hover:underline">
          ← {goal.name}
        </Link>
        <h1 className="text-xl font-semibold">Run optimizer</h1>
      </div>

      <div className="rounded-lg border border-neutral-200 bg-white p-4">
        <h2 className="mb-3 text-sm font-medium text-neutral-700">Sealed products to consider</h2>
        {productsLoading ? (
          <p className="text-sm text-neutral-400">Loading sealed products...</p>
        ) : !sealedProducts || sealedProducts.length === 0 ? (
          <p className="text-sm text-neutral-400">No sealed products found for this set.</p>
        ) : (
          <div className="max-h-64 space-y-1 overflow-y-auto">
            {sealedProducts.map((p) => (
              <label
                key={p.id}
                className={`flex items-center justify-between rounded px-2 py-1.5 text-sm ${
                  p.has_pull_rate_profile ? "" : "opacity-40"
                }`}
              >
                <span className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    disabled={!p.has_pull_rate_profile}
                    checked={selectedIds.has(p.id)}
                    onChange={() => toggle(p.id)}
                  />
                  {p.name}
                  {!p.has_pull_rate_profile && (
                    <span className="text-xs text-neutral-400">(no pull-rate data)</span>
                  )}
                </span>
                <span className="text-neutral-500">{formatMoney(p.market_price)}</span>
              </label>
            ))}
          </div>
        )}
        <p className="mt-2 text-xs text-neutral-400">
          Leave everything unchecked to consider every simulatable product for this set.
        </p>
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 rounded-lg border border-neutral-200 bg-white p-4 sm:grid-cols-3">
        <label className="text-sm">
          <span className="mb-1 block text-neutral-600">Objective</span>
          <select
            value={objective}
            onChange={(e) => setObjective(e.target.value as Objective)}
            className="w-full rounded border border-neutral-300 px-2 py-1"
          >
            {OBJECTIVES.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-neutral-600">Liquidation rate</span>
          <input
            type="number"
            step="0.05"
            min="0"
            max="1"
            value={liquidationRate}
            onChange={(e) => setLiquidationRate(Number(e.target.value))}
            className="w-full rounded border border-neutral-300 px-2 py-1"
          />
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-neutral-600">Resale floor ($)</span>
          <input
            type="number"
            step="0.5"
            min="0"
            value={resaleFloor}
            onChange={(e) => setResaleFloor(Number(e.target.value))}
            className="w-full rounded border border-neutral-300 px-2 py-1"
          />
        </label>
      </div>

      <button
        onClick={runOptimizer}
        disabled={runSimulation.isPending}
        className="mt-4 rounded bg-neutral-900 px-4 py-2 text-sm font-medium text-white hover:bg-neutral-700 disabled:opacity-50"
      >
        {runSimulation.isPending ? "Running..." : "Run optimizer"}
      </button>

      {runSimulation.isError && (
        <p className="mt-3 text-sm text-red-600">{(runSimulation.error as Error).message}</p>
      )}

      {response && (
        <div className="mt-8">
          {response.unsimulatable.length > 0 && (
            <p className="mb-4 text-xs text-amber-600">
              Not simulatable:{" "}
              {response.unsimulatable.map((u) => `${u.name} (${u.reason})`).join(", ")}
            </p>
          )}
          {Number(response.uncovered_needed_price_sum) > 0 && (
            <p className="mb-4 text-xs text-amber-600">
              {formatMoney(response.uncovered_needed_price_sum)} of needed cards fall outside
              this profile's pull-rate coverage and aren't reflected in the costs below.
            </p>
          )}

          <h2 className="mb-3 text-sm font-medium text-neutral-700">Ranked strategies</h2>
          <div className="overflow-hidden rounded-lg border border-neutral-200 bg-white">
            <table className="w-full text-sm">
              <thead className="border-b border-neutral-200 bg-neutral-50 text-left text-xs uppercase text-neutral-500">
                <tr>
                  <th className="px-3 py-2">Strategy</th>
                  <th className="px-3 py-2 text-right">Mean cost</th>
                  <th className="px-3 py-2 text-right">P90 cost</th>
                  <th className="px-3 py-2 text-right">Complete from sealed</th>
                  <th className="px-3 py-2 text-right">vs. singles</th>
                </tr>
              </thead>
              <tbody>
                {response.ranked.map((item) => {
                  const delta =
                    baseline && item !== baseline
                      ? item.result.mean - baseline.result.mean
                      : null;
                  return (
                    <tr
                      key={item.simulation_run_id}
                      className={`border-b border-neutral-100 last:border-0 ${
                        item === best ? "bg-emerald-50" : ""
                      }`}
                    >
                      <td className="px-3 py-2 font-medium text-neutral-800">
                        {strategyLabel(item.strategy, sealedProducts ?? [])}
                      </td>
                      <td className="px-3 py-2 text-right text-neutral-700">
                        ${item.result.mean.toFixed(2)}
                      </td>
                      <td className="px-3 py-2 text-right text-neutral-600">
                        ${item.result.p90.toFixed(2)}
                      </td>
                      <td className="px-3 py-2 text-right text-neutral-600">
                        {(item.result.p_complete_from_sealed * 100).toFixed(0)}%
                      </td>
                      <td className="px-3 py-2 text-right text-neutral-600">
                        {delta === null ? "—" : `${delta >= 0 ? "+" : ""}${delta.toFixed(2)}`}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {best && (
            <div className="mt-8 rounded-lg border border-neutral-200 bg-white p-4">
              <h2 className="mb-3 text-sm font-medium text-neutral-700">
                Cost distribution -- {strategyLabel(best.strategy, sealedProducts ?? [])}
              </h2>
              <CostHistogram result={best.result} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function CostHistogram({ result }: { result: RankedStrategyOut["result"] }) {
  const { histogram_counts, histogram_edges } = result;
  const data = histogram_counts.map((count, i) => ({
    bucket: `$${histogram_edges[i].toFixed(0)}`,
    count,
  }));

  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e5e5" />
          <XAxis dataKey="bucket" tick={{ fontSize: 10 }} interval={Math.ceil(data.length / 8)} />
          <YAxis tick={{ fontSize: 11 }} width={32} />
          <Tooltip formatter={(v: number) => [`${v} trials`, "Count"]} />
          <Bar dataKey="count" fill="#059669" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
