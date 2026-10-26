import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  useBinders,
  useCardFacets,
  useConvertGoalToCustom,
  useDeleteGoal,
  useEditGoalItems,
  useGoalDetail,
  useResyncGoal,
  useSets,
} from "../lib/queries";
import { formatMoney, formatPrice } from "../lib/types";
import { variantLabel } from "../lib/variants";
import {
  Button,
  ButtonLink,
  Callout,
  ErrorState,
  LoadingState,
  Page,
  PageHeader,
  Segmented,
  Select,
  Stat,
  Table,
  Tag,
  Td,
  Th,
  Tr,
} from "../components/ui";

const TYPE_LABEL: Record<string, string> = {
  set: "set",
  master_set: "master set",
  grand_master_set: "grand master set",
  filter: "live filter",
  custom: "custom list",
};

/** Human labels for the keys a filter goal stores (services/cards.CardQuery field names). */
const FILTER_LABEL: Record<string, string> = {
  q: "name contains",
  set_ids: "set",
  series: "era",
  rarities: "rarity",
  supertypes: "card type",
  types: "energy",
  subtypes: "subtype",
  artists: "illustrator",
  pokedex_numbers: "Pokémon",
  variants: "printing",
  variant_scope: "printings",
  min_price: "min $",
  max_price: "max $",
  year_from: "from",
  year_to: "to",
  // Legacy keys from before the card search existed.
  set_id: "set",
  rarity: "rarity",
  artist: "illustrator",
  supertype: "card type",
};

export default function GoalDetailPage() {
  const { goalId } = useParams<{ goalId: string }>();
  const navigate = useNavigate();
  const id = goalId ? Number(goalId) : undefined;
  const { data: goal, isLoading } = useGoalDetail(id);
  const { data: binders } = useBinders();
  const { data: facets } = useCardFacets();
  const { data: sets } = useSets();
  const deleteGoal = useDeleteGoal();
  const editItems = useEditGoalItems(id);
  const convert = useConvertGoalToCustom();
  const resync = useResyncGoal();
  const [exporting, setExporting] = useState(false);
  const [show, setShow] = useState<"needed" | "all">("needed");
  const [binderId, setBinderId] = useState<number | "">("");

  if (isLoading) return <LoadingState />;
  if (!goal) return <ErrorState message="Goal not found." />;

  const isCustom = goal.goal_type === "custom";
  const needed = goal.items.filter((i) => i.need_qty > 0);
  const rows = show === "needed" ? needed : goal.items;
  const multiSet = new Set(goal.items.map((i) => i.ptcg_set_id)).size > 1;

  async function exportMassEntry() {
    if (!goal) return;
    setExporting(true);
    try {
      const res = await fetch(`/api/v1/goals/${goal.id}/export/mass-entry`);
      if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
      const text = await res.text();
      const blob = new Blob([text], { type: "text/plain" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${goal.name.replace(/[^a-z0-9]+/gi, "-").toLowerCase()}-mass-entry.txt`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setExporting(false);
    }
  }

  function describeValue(key: string, value: unknown): string {
    const values = Array.isArray(value) ? value : [value];
    if (key === "pokedex_numbers") {
      return values
        .map((n) => facets?.species.find((s) => s.pokedex_number === n)?.name ?? `#${n}`)
        .join(", ");
    }
    if (key === "set_ids" || key === "set_id") {
      return values.map((n) => sets?.find((s) => s.id === n)?.name ?? `set ${n}`).join(", ");
    }
    if (key === "variant_scope") return value === "all" ? "every printing" : "one per card";
    return values.map(String).join(", ");
  }

  const filterEntries =
    goal.goal_type === "filter" && goal.filter_json
      ? Object.entries(goal.filter_json).filter(([k]) => k in FILTER_LABEL)
      : [];

  return (
    <Page width="narrow">
      <PageHeader
        title={goal.name}
        subtitle={`${TYPE_LABEL[goal.goal_type] ?? goal.goal_type} · ${goal.items.length} cards · target condition ${goal.target_condition}`}
        back={{ to: "/goals", label: "Goals" }}
      >
        {goal.set_id !== null ? (
          <ButtonLink to={`/goals/${goal.id}/simulate`}>Run optimizer</ButtonLink>
        ) : (
          <Button
            disabled
            title="The optimizer prices sealed product, which is per set. Goals spanning several sets get the singles cost below."
          >
            Run optimizer
          </Button>
        )}
        <Button
          variant="secondary"
          onClick={exportMassEntry}
          disabled={exporting || needed.length === 0}
        >
          {exporting ? "Exporting..." : "Export shopping list"}
        </Button>
        <Button
          variant="danger"
          onClick={() => deleteGoal.mutate(goal.id, { onSuccess: () => navigate("/goals") })}
          disabled={deleteGoal.isPending}
        >
          Delete
        </Button>
      </PageHeader>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Cards needed" value={String(goal.cost.n_cards)} />
        <Stat label="Subtotal" value={formatMoney(goal.cost.subtotal)} />
        <Stat
          label="Shipping"
          value={formatMoney(goal.cost.shipping)}
          hint={`${goal.cost.orders} orders`}
        />
        <Stat label="Singles total" value={formatMoney(goal.cost.total)} tone="positive" />
      </div>

      {goal.unpriced_count > 0 && (
        <Callout className="mt-3.5">
          {goal.unpriced_count} needed card{goal.unpriced_count === 1 ? "" : "s"} have no current
          price and are excluded from the total above.
        </Callout>
      )}

      {/* What builds this goal, and what you can do to it. */}
      <div className="mt-6 flex flex-wrap items-center gap-2.5 rounded-[11px] border border-line bg-raised px-4 py-3 shadow-panel">
        {isCustom ? (
          <>
            <span className="text-[12.5px] text-ink-2">A hand-picked list.</span>
            <div className="flex-1" />
            <ButtonLink to={`/cards?goal=${goal.id}`} variant="secondary">
              Add cards
            </ButtonLink>
          </>
        ) : (
          <>
            {filterEntries.length > 0 ? (
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="text-[12.5px] text-ink-2">Every card where</span>
                {filterEntries.map(([k, v]) => (
                  <Tag key={k} tone="accent">
                    {FILTER_LABEL[k]}: {describeValue(k, v)}
                  </Tag>
                ))}
              </div>
            ) : (
              <span className="text-[12.5px] text-ink-2">
                Built from{" "}
                {goal.goal_type === "grand_master_set"
                  ? "every printing in the set, stamps and promos included."
                  : goal.goal_type === "master_set"
                    ? "every printing pulled from the set's packs."
                    : "every card in the set."}
              </span>
            )}
            <div className="flex-1" />
            <Button
              variant="secondary"
              onClick={() => resync.mutate(goal.id)}
              disabled={resync.isPending}
              title="Re-run the rule, picking up cards from sets ingested since."
            >
              {resync.isPending ? "Resyncing..." : "Resync"}
            </Button>
            <Button
              variant="secondary"
              onClick={() => convert.mutate(goal.id)}
              disabled={convert.isPending}
              title="Freeze the current cards into a custom list you can add to and remove from. It stops following the rule."
            >
              Customize
            </Button>
          </>
        )}
      </div>
      {(editItems.isError || convert.isError || resync.isError) && (
        <Callout tone="danger" className="mt-3">
          {((editItems.error ?? convert.error ?? resync.error) as Error).message}
        </Callout>
      )}

      {/* Hand the goal to the binder designer as its card pool. */}
      <div className="mt-3 flex flex-wrap items-center gap-2.5 rounded-[11px] border border-line bg-raised px-4 py-3 shadow-panel">
        <span className="text-[12.5px] text-ink-2">Lay these cards out in a binder:</span>
        {binders && binders.length > 0 ? (
          <>
            <Select
              className="w-auto"
              value={binderId}
              aria-label="Binder"
              onChange={(e) => setBinderId(e.target.value ? Number(e.target.value) : "")}
            >
              <option value="">Choose a binder...</option>
              {binders.map((b) => (
                <option key={b.id} value={b.id}>
                  {b.name} ({b.rows}×{b.cols}, {b.pages} pages)
                </option>
              ))}
            </Select>
            <Button
              variant="secondary"
              disabled={binderId === "" || goal.items.length === 0}
              onClick={() => navigate(`/binders/${binderId}?goal=${goal.id}`)}
            >
              Open in designer
            </Button>
          </>
        ) : (
          <ButtonLink to="/binders" variant="secondary">
            Create a binder first
          </ButtonLink>
        )}
      </div>

      <div className="mb-3 mt-8 flex items-center gap-3">
        <h2 className="text-[14px] font-semibold text-ink">
          {show === "needed" ? "Still needed" : "Every card in this goal"}
        </h2>
        <div className="flex-1" />
        <Segmented
          value={show}
          onChange={setShow}
          options={[
            { value: "needed", label: `needed (${needed.length})` },
            { value: "all", label: `all (${goal.items.length})` },
          ]}
        />
      </div>
      <Table
        head={
          <>
            <Th className="w-12" />
            <Th className="w-16">#</Th>
            <Th>Card</Th>
            {multiSet && <Th>Set</Th>}
            <Th>Variant</Th>
            <Th>Rarity</Th>
            <Th className="text-right">Price</Th>
            <Th className="text-right">{show === "needed" ? "Need" : "Owned"}</Th>
            {isCustom && <Th className="w-10" />}
          </>
        }
      >
        {rows.length === 0 ? (
          <Tr>
            <Td colSpan={9} className="py-10 text-center text-[12.5px] text-ink-3">
              {goal.items.length === 0
                ? isCustom
                  ? "No cards yet -- use Add cards to pick some."
                  : "No cards match this goal's rule."
                : "Everything in this goal is already owned."}
            </Td>
          </Tr>
        ) : (
          rows.map((item) => (
            <Tr key={item.card_variant_id}>
              <Td className="py-1.5">
                {item.image_small ? (
                  <img
                    src={item.image_small}
                    alt=""
                    loading="lazy"
                    className="aspect-card w-7 rounded-[3px] bg-well object-cover"
                  />
                ) : (
                  <div className="hatch aspect-card w-7 rounded-[3px] border border-line-card" />
                )}
              </Td>
              <Td className="font-mono text-[11.5px] text-accent-text">{item.number}</Td>
              <Td className="font-medium text-ink">{item.card_name}</Td>
              {multiSet && <Td className="text-ink-3">{item.set_name}</Td>}
              <Td className="text-ink-3">
                {variantLabel(item.variant, item.variant_label)}
              </Td>
              <Td className="text-ink-3">{item.rarity ?? "—"}</Td>
              <Td className="text-right font-mono text-[12px]">
                {formatPrice(item.market_price)}
              </Td>
              <Td className="text-right font-mono text-[12px] font-medium text-ink">
                {show === "needed" ? item.need_qty : item.owned_qty}
              </Td>
              {isCustom && (
                <Td className="text-right">
                  <button
                    type="button"
                    aria-label={`Remove ${item.card_name} from this goal`}
                    title="Remove from goal"
                    disabled={editItems.isPending}
                    onClick={() => editItems.mutate({ remove: [item.card_variant_id] })}
                    className="text-[14px] text-ink-4 hover:text-danger-text"
                  >
                    &times;
                  </button>
                </Td>
              )}
            </Tr>
          ))
        )}
      </Table>
    </Page>
  );
}
