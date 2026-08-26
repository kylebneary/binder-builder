import { useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  useGoalDetail,
  useRunSensitivity,
  useRunSimulation,
  useSealedProducts,
  useSets,
} from "../lib/queries";
import type {
  Objective,
  RankedStrategyOut,
  SealedProductOut,
  SensitivityOut,
  SimulateIn,
} from "../lib/types";
import { formatMoney, parseMoney } from "../lib/types";
import { tooltipStyles, useChartColors } from "../lib/chartTheme";
import {
  AccentPanel,
  Button,
  Callout,
  ErrorState,
  Field,
  Input,
  LoadingState,
  Page,
  PageHeader,
  Panel,
  SectionLabel,
  Select,
  Table,
  Tag,
  Td,
  Th,
  Tr,
} from "../components/ui";

const OBJECTIVES: { value: Objective; label: string }[] = [
  { value: "min_expected_cost", label: "Minimize expected cost" },
  { value: "min_p90_cost", label: "Minimize worst-case (p90) cost" },
];

function strategyLabel(
  strategy: RankedStrategyOut["strategy"],
  products: SealedProductOut[],
): string {
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
  const runSensitivity = useRunSensitivity(id);

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
    runSimulation.mutate(body, { onSuccess: () => runSensitivity.reset() });
  }

  function checkSensitivity(best: RankedStrategyOut) {
    const unitsAsNumbers: Record<number, number> = {};
    for (const [pid, qty] of Object.entries(best.strategy.units)) {
      unitsAsNumbers[Number(pid)] = qty;
    }
    runSensitivity.mutate({
      sealed_product_ids: unitsAsNumbers,
      liquidation_rate: liquidationRate,
      resale_floor: resaleFloor,
    });
  }

  if (goalLoading) return <LoadingState />;
  if (!goal) return <ErrorState message="Goal not found." />;

  const response = runSimulation.data;
  const baseline = response?.ranked.find((r) => Object.keys(r.strategy.units).length === 0);
  const best = response?.ranked[0];
  const products = sealedProducts ?? [];

  return (
    <Page>
      <PageHeader
        title="Completion solver"
        subtitle={`${goal.cost.n_cards} cards left · ${goal.name}`}
        back={{ to: `/goals/${goal.id}`, label: goal.name }}
      />

      <div className="grid gap-4 lg:grid-cols-12">
        {/* ------------------------------------------------ sealed product picker */}
        <Panel className="flex flex-col p-4 lg:col-span-7">
          <SectionLabel className="mb-3">Sealed products to consider</SectionLabel>
          {productsLoading ? (
            <p className="text-[12.5px] text-ink-3">Loading sealed products...</p>
          ) : products.length === 0 ? (
            <p className="text-[12.5px] text-ink-3">No sealed products found for this set.</p>
          ) : (
            <div className="-mx-1 max-h-72 space-y-0.5 overflow-y-auto px-1">
              {products.map((p) => {
                const disabled = !p.has_pull_rate_profile;
                return (
                  <label
                    key={p.id}
                    className={`flex items-center justify-between gap-3 rounded-lg px-2.5 py-2 text-[13px] transition-colors ${
                      disabled ? "opacity-45" : "cursor-pointer hover:bg-inset"
                    }`}
                  >
                    <span className="flex min-w-0 items-center gap-2.5">
                      <input
                        type="checkbox"
                        disabled={disabled}
                        checked={selectedIds.has(p.id)}
                        onChange={() => toggle(p.id)}
                        className="h-3.5 w-3.5 flex-none accent-[var(--accent)]"
                      />
                      <span className="truncate text-ink-2">{p.name}</span>
                      {disabled && <Tag>NO PULL RATES</Tag>}
                    </span>
                    <span className="flex-none font-mono text-[12px] text-ink-3">
                      {formatMoney(p.market_price)}
                    </span>
                  </label>
                );
              })}
            </div>
          )}
          <p className="mt-3 text-[11.5px] leading-[1.55] text-ink-4">
            Leave everything unchecked to consider every simulatable product for this set.
          </p>
        </Panel>

        {/* ---------------------------------------------------------- constraints */}
        <Panel className="flex flex-col gap-3.5 p-4 lg:col-span-5">
          <SectionLabel>Constraints</SectionLabel>
          <Field label="Objective">
            <Select
              value={objective}
              onChange={(e) => setObjective(e.target.value as Objective)}
            >
              {OBJECTIVES.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Liquidation rate">
              <Input
                type="number"
                step="0.05"
                min="0"
                max="1"
                value={liquidationRate}
                onChange={(e) => setLiquidationRate(Number(e.target.value))}
              />
            </Field>
            <Field label="Resale floor ($)">
              <Input
                type="number"
                step="0.5"
                min="0"
                value={resaleFloor}
                onChange={(e) => setResaleFloor(Number(e.target.value))}
              />
            </Field>
          </div>
          <Button onClick={runOptimizer} disabled={runSimulation.isPending} className="mt-1 w-full">
            {runSimulation.isPending ? "Solving..." : "Solve"}
          </Button>
          <p className="text-[10.5px] leading-[1.5] text-ink-4">
            Pull rates are community estimates, not published odds — read every number below as an
            estimate with a confidence interval.
          </p>
        </Panel>
      </div>

      {runSimulation.isError && (
        <Callout tone="danger" className="mt-4">
          {(runSimulation.error as Error).message}
        </Callout>
      )}

      {response && (
        <div className="mt-8 flex flex-col gap-4">
          {response.unsimulatable.length > 0 && (
            <Callout>
              Not simulatable:{" "}
              {response.unsimulatable.map((u) => `${u.name} (${u.reason})`).join(", ")}
            </Callout>
          )}
          {Number(response.uncovered_needed_price_sum) > 0 && (
            <Callout>
              {formatMoney(response.uncovered_needed_price_sum)} of needed cards fall outside this
              profile&rsquo;s pull-rate coverage and aren&rsquo;t reflected in the costs below.
            </Callout>
          )}

          {best && (
            <CheapestPath
              best={best}
              baseline={baseline}
              products={products}
              nTrials={best.result.n_trials}
            />
          )}

          <div>
            <h2 className="mb-3 text-[14px] font-semibold text-ink">Ranked strategies</h2>
            <Table
              head={
                <>
                  <Th>Strategy</Th>
                  <Th className="text-right">Mean cost</Th>
                  <Th className="text-right">P90 cost</Th>
                  <Th className="text-right">Complete from sealed</Th>
                  <Th className="text-right">vs. singles</Th>
                </>
              }
            >
              {response.ranked.map((item) => {
                const delta =
                  baseline && item !== baseline ? item.result.mean - baseline.result.mean : null;
                return (
                  <Tr key={item.simulation_run_id} highlight={item === best}>
                    <Td className="font-medium text-ink">
                      {strategyLabel(item.strategy, products)}
                    </Td>
                    <Td className="text-right font-mono text-[12px] font-medium text-ink">
                      ${item.result.mean.toFixed(2)}
                    </Td>
                    <Td className="text-right font-mono text-[12px]">
                      ${item.result.p90.toFixed(2)}
                    </Td>
                    <Td className="text-right font-mono text-[12px]">
                      {(item.result.p_complete_from_sealed * 100).toFixed(0)}%
                    </Td>
                    <Td
                      className={`text-right font-mono text-[12px] ${
                        delta !== null && delta < 0 ? "text-accent-text" : "text-ink-3"
                      }`}
                    >
                      {delta === null ? "—" : `${delta >= 0 ? "+" : ""}${delta.toFixed(2)}`}
                    </Td>
                  </Tr>
                );
              })}
            </Table>
          </div>

          {best && (
            <Panel className="p-4">
              <SectionLabel className="mb-4">
                Cost distribution · {strategyLabel(best.strategy, products)}
              </SectionLabel>
              <CostHistogram result={best.result} />
            </Panel>
          )}

          {best && (
            <Panel className="p-4">
              <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                <SectionLabel>
                  Sensitivity · {strategyLabel(best.strategy, products)} vs. singles
                </SectionLabel>
                <Button
                  variant="secondary"
                  onClick={() => checkSensitivity(best)}
                  disabled={runSensitivity.isPending}
                  className="px-3 py-1.5 text-[12px]"
                >
                  {runSensitivity.isPending ? "Checking..." : "Check sensitivity"}
                </Button>
              </div>
              {runSensitivity.isError && (
                <Callout tone="danger">{(runSensitivity.error as Error).message}</Callout>
              )}
              {runSensitivity.data && <SensitivityPanel sensitivity={runSensitivity.data} />}
              {!runSensitivity.data && !runSensitivity.isPending && !runSensitivity.isError && (
                <p className="text-[12.5px] leading-[1.6] text-ink-3">
                  Perturbs pull rates, liquidation rate, sealed price, and price basis by plausible
                  amounts to check whether this recommendation still holds.
                </p>
              )}
            </Panel>
          )}
        </div>
      )}
    </Page>
  );
}

/** The mockup's "cheapest path" hero: one big mono number, the singles baseline it beats, and
 *  the sealed units that make it up. */
function CheapestPath({
  best,
  baseline,
  products,
  nTrials,
}: {
  best: RankedStrategyOut;
  baseline?: RankedStrategyOut;
  products: SealedProductOut[];
  nTrials: number;
}) {
  const units = Object.entries(best.strategy.units);
  const saving = baseline ? baseline.result.mean - best.result.mean : null;

  return (
    <AccentPanel className="flex flex-col gap-4 p-5">
      <div className="flex flex-col gap-1">
        <SectionLabel className="text-accent-text">Cheapest path</SectionLabel>
        <span className="font-mono text-[30px] font-bold leading-none tracking-[-1px] text-ink">
          ${best.result.mean.toFixed(2)}
        </span>
        {baseline && (
          <span className="text-[11.5px] text-ink-3">
            vs ${baseline.result.mean.toFixed(2)} buying every card as a single
            {saving !== null && saving > 0 ? ` · saves $${saving.toFixed(2)}` : ""}
          </span>
        )}
      </div>

      <div className="grid grid-cols-3 gap-3 border-t border-accent-line pt-3.5">
        <HeroStat label="P50" value={`$${best.result.p50.toFixed(0)}`} />
        <HeroStat label="P90" value={`$${best.result.p90.toFixed(0)}`} />
        <HeroStat
          label="Complete from sealed"
          value={`${(best.result.p_complete_from_sealed * 100).toFixed(0)}%`}
        />
      </div>

      {units.length > 0 && (
        <div className="flex flex-col gap-2 border-t border-accent-line pt-3.5">
          {units.map(([pid, qty]) => {
            const product = products.find((p) => p.id === Number(pid));
            const unitPrice = parseMoney(product?.market_price ?? null);
            return (
              <div key={pid} className="flex items-center gap-2.5">
                <span aria-hidden="true" className="h-6 w-[3px] flex-none rounded-sm bg-warn" />
                <div className="flex min-w-0 flex-1 flex-col">
                  <span className="truncate text-[12.5px] font-medium text-ink">
                    {product?.name ?? `Product ${pid}`} &times;{qty}
                  </span>
                  {product?.packs_per_unit && (
                    <span className="text-[11px] text-ink-3">
                      {product.packs_per_unit * qty} packs
                    </span>
                  )}
                </div>
                <span className="flex-none font-mono text-[12.5px] text-ink">
                  {unitPrice === null ? "—" : `$${(unitPrice * qty).toFixed(2)}`}
                </span>
              </div>
            );
          })}
        </div>
      )}

      <p className="font-mono text-[10.5px] leading-[1.5] text-ink-4">
        {nTrials.toLocaleString()} pull simulations · prices from last sync · pull rates are
        estimates
      </p>
    </AccentPanel>
  );
}

function HeroStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-ink-3">
        {label}
      </span>
      <span className="font-mono text-[16px] font-bold text-ink">{value}</span>
    </div>
  );
}

function SensitivityPanel({ sensitivity }: { sensitivity: SensitivityOut }) {
  const c = useChartColors();
  const t = tooltipStyles(c);
  const data = sensitivity.factors.map((f) => ({
    name: f.name,
    base: Math.min(f.low_cost, f.high_cost),
    range: Math.abs(f.high_cost - f.low_cost),
    low: f.low_cost,
    high: f.high_cost,
  }));

  return (
    <div>
      {!sensitivity.robust && (
        <Callout className="mb-4">
          This recommendation is not robust: at least one plausible pull-rate or pricing
          perturbation flips which of these two options is actually cheaper.
        </Callout>
      )}
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} layout="vertical" margin={{ left: 8, right: 16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={c.grid} horizontal={false} />
            <XAxis
              type="number"
              tick={{ fontSize: 11, fill: c.axis }}
              stroke={c.grid}
              tickLine={false}
              tickFormatter={(v: number) => `$${v.toFixed(0)}`}
            />
            <YAxis
              type="category"
              dataKey="name"
              tick={{ fontSize: 11, fill: c.axis }}
              stroke={c.grid}
              tickLine={false}
              width={170}
            />
            <Tooltip
              formatter={(
                _value: number,
                _key: string,
                item: { payload?: { low: number; high: number } },
              ) => {
                const p = item.payload;
                return p ? [`$${p.low.toFixed(2)} - $${p.high.toFixed(2)}`, "Range"] : ["", ""];
              }}
              contentStyle={t.contentStyle}
              labelStyle={t.labelStyle}
              itemStyle={t.itemStyle}
              cursor={t.cursor}
            />
            <ReferenceLine x={sensitivity.strategy_mean} stroke={c.reference} strokeDasharray="4 4" />
            <Bar dataKey="base" stackId="a" fill="transparent" />
            <Bar dataKey="range" stackId="a" fill={c.warn} radius={2} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <p className="mt-2.5 text-[11px] text-ink-4">
        Dashed line: this strategy&rsquo;s mean cost (${sensitivity.strategy_mean.toFixed(2)}). Bars
        show the cost range under each perturbation.
      </p>
    </div>
  );
}

function CostHistogram({ result }: { result: RankedStrategyOut["result"] }) {
  const c = useChartColors();
  const t = tooltipStyles(c);
  const { histogram_counts, histogram_edges } = result;
  const data = histogram_counts.map((count, i) => ({
    bucket: `$${histogram_edges[i].toFixed(0)}`,
    count,
  }));

  return (
    <div className="h-56">
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={c.grid} vertical={false} />
          <XAxis
            dataKey="bucket"
            tick={{ fontSize: 10, fill: c.axis }}
            stroke={c.grid}
            tickLine={false}
            interval={Math.ceil(data.length / 8)}
          />
          <YAxis
            tick={{ fontSize: 11, fill: c.axis }}
            stroke={c.grid}
            tickLine={false}
            width={36}
          />
          <Tooltip
            formatter={(v: number) => [`${v} trials`, "Count"]}
            contentStyle={t.contentStyle}
            labelStyle={t.labelStyle}
            itemStyle={t.itemStyle}
            cursor={t.cursor}
          />
          <Bar dataKey="count" fill={c.accent} radius={[2, 2, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
