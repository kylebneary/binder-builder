import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  useCardFacets,
  useCardSearch,
  useCreateGoal,
  useEditGoalItems,
  useGoals,
  useSets,
} from "../lib/queries";
import type { CardQuery, CardSearchItem, CardSort, VariantOut } from "../lib/types";
import { formatMoney, parseMoney } from "../lib/types";
import {
  Button,
  Callout,
  Chip,
  EmptyState,
  Field,
  Input,
  LoadingState,
  Page,
  PageHeader,
  Panel,
  SectionLabel,
  Segmented,
  Select,
  Tag,
} from "../components/ui";

/**
 * Catalogue-wide card search, and the builder for custom goals.
 *
 * Every filter lives in the URL rather than component state, so a search can be bookmarked and
 * the goal templates can link straight into a pre-filled one (`/cards?artist=Mitsuhiro+Arita`).
 * `?goal=<id>` switches the page into "add to this goal" mode.
 *
 * Selection is by card variant, the unit a goal holds. "Select all N matching" does not page
 * through the results client-side: it sends the query itself and the server expands it.
 */

const PAGE_SIZE = 60;

// URL key <-> CardQuery field. Repeated keys carry lists.
const LIST_KEYS = {
  set: "set_ids",
  series: "series",
  rarity: "rarities",
  supertype: "supertypes",
  type: "types",
  subtype: "subtypes",
  artist: "artists",
  dex: "pokedex_numbers",
  variant: "variants",
} as const;
const NUMERIC_LISTS = new Set(["set", "dex"]);

function queryFromParams(sp: URLSearchParams): CardQuery {
  const query: CardQuery = {};
  for (const [key, field] of Object.entries(LIST_KEYS)) {
    const values = sp.getAll(key);
    if (values.length === 0) continue;
    (query as Record<string, unknown>)[field] = NUMERIC_LISTS.has(key)
      ? values.map(Number).filter((n) => !Number.isNaN(n))
      : values;
  }
  if (sp.get("q")) query.q = sp.get("q");
  if (sp.get("scope") === "all") query.variant_scope = "all";
  const owned = sp.get("owned");
  if (owned === "owned" || owned === "missing") query.owned = owned;
  if (sp.get("min")) query.min_price = sp.get("min");
  if (sp.get("max")) query.max_price = sp.get("max");
  if (sp.get("from")) query.year_from = Number(sp.get("from"));
  if (sp.get("to")) query.year_to = Number(sp.get("to"));
  return query;
}

/** Mirrors CardQuery.describes_anything on the backend: a live goal needs a real filter. */
function describesAnything(q: CardQuery): boolean {
  return Boolean(
    q.q ||
      q.min_price ||
      q.max_price ||
      q.year_from ||
      q.year_to ||
      Object.values(LIST_KEYS).some((f) => ((q as Record<string, unknown>)[f] as unknown[])?.length),
  );
}

interface PickOption {
  value: string;
  label: string;
  count?: number;
}

/**
 * Pick several values for one filter. Short lists (rarity, type) use a dropdown; long ones
 * (artist, Pokemon) a type-ahead input over a datalist, since a 1,000-entry <select> is unusable.
 */
function MultiPick({
  label,
  options,
  selected,
  onChange,
  searchable = false,
}: {
  label: string;
  options: PickOption[];
  selected: string[];
  onChange: (values: string[]) => void;
  searchable?: boolean;
}) {
  const [draft, setDraft] = useState("");
  const byValue = useMemo(() => new Map(options.map((o) => [o.value, o])), [options]);
  const byLabel = useMemo(
    () => new Map(options.map((o) => [o.label.toLowerCase(), o])),
    [options],
  );
  const listId = `pick-${label.replace(/\W+/g, "-").toLowerCase()}`;

  function add(value: string) {
    if (value && !selected.includes(value)) onChange([...selected, value]);
  }

  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[12.5px] font-medium text-ink-2">{label}</span>
      {searchable ? (
        <>
          <Input
            list={listId}
            value={draft}
            placeholder="Type to search..."
            onChange={(e) => {
              const hit = byLabel.get(e.target.value.toLowerCase());
              if (hit) {
                add(hit.value);
                setDraft("");
              } else {
                setDraft(e.target.value);
              }
            }}
          />
          <datalist id={listId}>
            {options.map((o) => (
              <option key={o.value} value={o.label}>
                {o.count !== undefined ? `${o.count} cards` : undefined}
              </option>
            ))}
          </datalist>
        </>
      ) : (
        <Select
          value=""
          aria-label={label}
          onChange={(e) => {
            add(e.target.value);
          }}
        >
          <option value="">Add...</option>
          {options
            .filter((o) => !selected.includes(o.value))
            .map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
                {o.count !== undefined ? ` (${o.count})` : ""}
              </option>
            ))}
        </Select>
      )}
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {selected.map((v) => (
            <Chip
              key={v}
              active
              type="button"
              title="Remove"
              onClick={() => onChange(selected.filter((s) => s !== v))}
            >
              {byValue.get(v)?.label ?? v} &times;
            </Chip>
          ))}
        </div>
      )}
    </div>
  );
}

// Collector-facing names for the variant enum. Anything new from the price feed falls back to
// its enum value with spaces.
const VARIANT_LABELS: Record<string, string> = {
  normal: "Normal",
  holofoil: "Holo",
  reverse_holofoil: "Reverse holo",
  first_edition_normal: "1st Edition",
  first_edition_holofoil: "1st Edition holo",
  unlimited_normal: "Unlimited",
  unlimited_holofoil: "Unlimited holo",
  shadowless_normal: "Shadowless",
  shadowless_holofoil: "Shadowless holo",
  poke_ball_holo: "Poké Ball holo",
  master_ball_holo: "Master Ball holo",
};

/** Base printings are named here; tagged printings carry their label from the server
 * (data/printing_tags.yaml). */
function variantLabel(v: string, label?: string | null) {
  return label ?? VARIANT_LABELS[v] ?? v.replace(/_/g, " ");
}

function cardPrice(card: CardSearchItem): string | null {
  let best: number | null = null;
  let raw: string | null = null;
  for (const v of card.variants) {
    const n = parseMoney(v.market_price);
    if (n !== null && (best === null || n > best)) {
      best = n;
      raw = v.market_price;
    }
  }
  return raw;
}

function ResultTile({
  card,
  selected,
  showVariants,
  onToggleCard,
  onToggleVariant,
}: {
  card: CardSearchItem;
  selected: Set<number>;
  showVariants: boolean;
  onToggleCard: () => void;
  onToggleVariant: (v: VariantOut) => void;
}) {
  const picked = card.variants.filter((v) => selected.has(v.id)).length;
  const allPicked = picked === card.variants.length && picked > 0;
  return (
    <div
      className={`flex flex-col gap-1.5 rounded-[10px] border p-1.5 transition-colors ${
        allPicked ? "border-accent bg-accent-surface" : picked ? "border-accent-line" : "border-line bg-raised"
      }`}
    >
      <button
        type="button"
        onClick={onToggleCard}
        aria-pressed={allPicked}
        aria-label={`${allPicked ? "Deselect" : "Select"} ${card.name}, ${card.set_name} ${card.number}`}
        className="flex flex-col gap-1.5 text-left"
      >
        {/* Status row above the art rather than over it, so no artwork is covered. Fixed
            height whether or not the card is owned, so every tile in a row lines up. */}
        <span className="flex h-5 items-center justify-between px-0.5">
          {card.is_owned ? <Tag tone="accent">OWNED</Tag> : <span />}
          <span
            className={`flex h-5 w-5 items-center justify-center rounded-full border text-[11px] font-bold ${
              allPicked
                ? "border-accent bg-accent text-accent-fg"
                : "border-line-strong bg-surface text-transparent"
            }`}
          >
            ✓
          </span>
        </span>
        {card.image_small ? (
          <img
            src={card.image_small}
            alt=""
            loading="lazy"
            className="aspect-card w-full rounded-md bg-well object-cover"
          />
        ) : (
          <div className="hatch aspect-card w-full rounded-md border border-line-card" />
        )}
      </button>
      <div className="flex min-w-0 flex-col px-0.5">
        <span className="truncate text-[12px] font-medium text-ink" title={card.name}>
          {card.name}
        </span>
        <span className="truncate text-[10.5px] text-ink-3" title={card.set_name}>
          {card.set_name} · <span className="font-mono">{card.number}</span>
        </span>
        <span className="flex justify-between gap-1 text-[10.5px]">
          <span className="truncate text-ink-3">{card.rarity ?? "—"}</span>
          <span className="font-mono text-ink-2">{formatMoney(cardPrice(card))}</span>
        </span>
      </div>
      {showVariants && card.variants.length > 0 && (
        <div className="flex flex-wrap gap-1 px-0.5">
          {card.variants.map((v) => (
            <button
              key={v.id}
              type="button"
              onClick={() => onToggleVariant(v)}
              aria-pressed={selected.has(v.id)}
              className={`rounded px-1.5 py-[2px] font-mono text-[9.5px] ${
                selected.has(v.id) ? "bg-accent text-accent-fg" : "bg-inset text-ink-3 hover:text-ink"
              } ${v.is_special ? "border border-dashed border-warn-line" : ""}`}
              title={`${variantLabel(v.variant, v.label)} · ${formatMoney(v.market_price)}${
                v.is_special ? " · stamp/promo (Grand Master Set)" : ""
              }${v.owned_quantity > 0 ? " · owned" : ""}`}
            >
              {variantLabel(v.variant, v.label)}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default function CardSearchPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const query = useMemo(() => queryFromParams(params), [params]);
  const targetGoalId = params.get("goal") ? Number(params.get("goal")) : undefined;
  const sort = (params.get("sort") as CardSort) || "newest";
  const page = Number(params.get("page") ?? 0);

  const { data: facets } = useCardFacets();
  const { data: sets } = useSets();
  const { data: goals } = useGoals();
  const { data: result, isLoading, isFetching, error } = useCardSearch({
    ...query,
    sort,
    offset: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });
  const createGoal = useCreateGoal();

  const customGoals = (goals ?? []).filter((g) => g.goal_type === "custom");
  const [addGoalId, setAddGoalId] = useState<number | "">(targetGoalId ?? "");
  useEffect(() => setAddGoalId(targetGoalId ?? ""), [targetGoalId]);
  const editGoal = useEditGoalItems(addGoalId === "" ? undefined : addGoalId);
  const targetGoal = goals?.find((g) => g.id === targetGoalId);

  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [allMatching, setAllMatching] = useState(false);
  const [goalName, setGoalName] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  // The name box is typed into a character at a time; committing each keystroke to the URL
  // would refetch per character, so it settles for a moment first.
  const [nameDraft, setNameDraft] = useState(query.q ?? "");
  useEffect(() => setNameDraft(query.q ?? ""), [query.q]);
  useEffect(() => {
    if (nameDraft === (query.q ?? "")) return;
    const t = setTimeout(() => update({ q: nameDraft ? [nameDraft] : [] }), 300);
    return () => clearTimeout(t);
  }, [nameDraft]); // only the draft: `update` and `query` change on every render

  /** Replace some URL keys, resetting to the first page; a filter change also voids "all
   * matching", which named the old query. */
  function update(changes: Record<string, string[]>, keepPage = false) {
    const next = new URLSearchParams(params);
    for (const [key, values] of Object.entries(changes)) {
      next.delete(key);
      for (const v of values) if (v !== "") next.append(key, v);
    }
    if (!keepPage) {
      next.delete("page");
      setAllMatching(false);
    }
    setParams(next, { replace: true });
  }

  function clearFilters() {
    const next = new URLSearchParams();
    if (targetGoalId) next.set("goal", String(targetGoalId));
    setParams(next, { replace: true });
    setAllMatching(false);
  }

  function toggleVariants(ids: number[], on: boolean) {
    setSelected((prev) => {
      const next = new Set(prev);
      for (const id of ids) {
        if (on) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }

  const selectionQuery = allMatching ? query : null;
  const selectionCount = allMatching ? (result?.total ?? 0) : selected.size;
  const pickedIds = [...selected];
  const hasSelection = allMatching || selected.size > 0;

  function finish(message: string) {
    setSelected(new Set());
    setAllMatching(false);
    setNotice(message);
  }

  function saveAsList() {
    createGoal.mutate(
      {
        name: goalName.trim(),
        goal_type: "custom",
        card_variant_ids: pickedIds,
        query: selectionQuery,
      },
      { onSuccess: (goal) => navigate(`/goals/${goal.id}`) },
    );
  }

  function saveAsLive() {
    createGoal.mutate(
      { name: goalName.trim(), goal_type: "filter", query },
      { onSuccess: (goal) => navigate(`/goals/${goal.id}`) },
    );
  }

  function addToGoal() {
    if (addGoalId === "") return;
    editGoal.mutate(
      { add: pickedIds, add_query: selectionQuery },
      {
        onSuccess: (r) => {
          const name = goals?.find((g) => g.id === addGoalId)?.name ?? "the goal";
          finish(`Added ${r.added} to ${name} (${r.item_count} cards now).`);
        },
      },
    );
  }

  const str = (values: (string | number)[] | undefined) => (values ?? []).map(String);
  const facetOptions = (values: { value: string; count: number }[] | undefined) =>
    (values ?? []).map((f) => ({ value: f.value, label: f.value, count: f.count }));
  const pageCount = result ? Math.max(1, Math.ceil(result.total / PAGE_SIZE)) : 1;
  const currentYear = new Date().getFullYear();

  return (
    <Page>
      <PageHeader
        title={targetGoal ? `Add cards to ${targetGoal.name}` : "Cards"}
        subtitle={
          targetGoal
            ? "Filter, pick, and add -- or add everything that matches."
            : "Search every card by any attribute, then save what you pick as a goal."
        }
        back={targetGoal ? { to: `/goals/${targetGoal.id}`, label: targetGoal.name } : undefined}
      />

      <div className="flex flex-col gap-5 lg:flex-row">
        <Panel className="flex w-full flex-none flex-col gap-3.5 p-4 lg:w-72">
          <div className="flex items-center justify-between">
            <SectionLabel>Filters</SectionLabel>
            <button
              type="button"
              onClick={clearFilters}
              className="font-mono text-[10.5px] text-ink-3 underline hover:text-ink"
            >
              clear all
            </button>
          </div>

          <Field label="Name contains">
            <Input
              value={nameDraft}
              onChange={(e) => setNameDraft(e.target.value)}
              placeholder="Charizard, Professor..."
            />
          </Field>

          <MultiPick
            label="Pokémon"
            searchable
            options={(facets?.species ?? []).map((s) => ({
              value: String(s.pokedex_number),
              label: s.name,
              count: s.count,
            }))}
            selected={str(query.pokedex_numbers)}
            onChange={(v) => update({ dex: v })}
          />
          <p className="-mt-2 text-[10.5px] leading-snug text-ink-3">
            By Pokédex number: every printing of the species, its ex/V forms and tag teams, but
            not Mewtwo for Mew.
          </p>

          <MultiPick
            label="Illustrator"
            searchable
            options={facetOptions(facets?.artists)}
            selected={str(query.artists)}
            onChange={(v) => update({ artist: v })}
          />

          <MultiPick
            label="Set"
            searchable
            options={(sets ?? []).map((s) => ({ value: String(s.id), label: s.name }))}
            selected={str(query.set_ids)}
            onChange={(v) => update({ set: v })}
          />
          <MultiPick
            label="Era"
            options={facetOptions(facets?.series)}
            selected={str(query.series)}
            onChange={(v) => update({ series: v })}
          />
          <MultiPick
            label="Rarity"
            options={facetOptions(facets?.rarities)}
            selected={str(query.rarities)}
            onChange={(v) => update({ rarity: v })}
          />
          <MultiPick
            label="Card type"
            options={facetOptions(facets?.supertypes)}
            selected={str(query.supertypes)}
            onChange={(v) => update({ supertype: v })}
          />
          <MultiPick
            label="Energy type"
            options={facetOptions(facets?.types)}
            selected={str(query.types)}
            onChange={(v) => update({ type: v })}
          />
          <MultiPick
            label="Subtype"
            options={facetOptions(facets?.subtypes)}
            selected={str(query.subtypes)}
            onChange={(v) => update({ subtype: v })}
          />

          <div className="grid grid-cols-2 gap-2">
            <Field label="Released from">
              <Input
                type="number"
                min={1996}
                max={currentYear}
                defaultValue={query.year_from ?? ""}
                key={`from-${query.year_from}`}
                onBlur={(e) => update({ from: [e.target.value] })}
                placeholder="1999"
              />
            </Field>
            <Field label="to">
              <Input
                type="number"
                min={1996}
                max={currentYear}
                defaultValue={query.year_to ?? ""}
                key={`to-${query.year_to}`}
                onBlur={(e) => update({ to: [e.target.value] })}
                placeholder={String(currentYear)}
              />
            </Field>
            <Field label="Min price $">
              <Input
                inputMode="decimal"
                defaultValue={query.min_price ?? ""}
                key={`min-${query.min_price}`}
                onBlur={(e) => update({ min: [e.target.value.trim()] })}
              />
            </Field>
            <Field label="Max price $">
              <Input
                inputMode="decimal"
                defaultValue={query.max_price ?? ""}
                key={`max-${query.max_price}`}
                onBlur={(e) => update({ max: [e.target.value.trim()] })}
              />
            </Field>
          </div>

          <div className="flex flex-col gap-1.5">
            <span className="text-[12.5px] font-medium text-ink-2">Collection</span>
            <Segmented
              value={query.owned ?? "any"}
              onChange={(v) => update({ owned: v === "any" ? [] : [v] })}
              options={[
                { value: "any", label: "any" },
                { value: "missing", label: "missing" },
                { value: "owned", label: "owned" },
              ]}
            />
          </div>

          {query.variant_scope === "all" && (
            <MultiPick
              label="Only these printings"
              options={(facets?.variants ?? []).map((f) => ({
                value: f.value,
                label: variantLabel(f.value, f.label),
                count: f.count,
              }))}
              selected={str(query.variants)}
              onChange={(v) => update({ variant: v })}
            />
          )}
        </Panel>

        <div className="flex min-w-0 flex-1 flex-col gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <span className="font-mono text-[12px] text-ink-2">
              {result ? `${result.total.toLocaleString()} cards` : "—"}
              {isFetching && !isLoading && <span className="ml-2 text-ink-4">updating</span>}
            </span>
            {result && result.total > 0 && (
              <Button
                variant="secondary"
                className="px-3 py-1.5 text-[12px]"
                onClick={() => setAllMatching((v) => !v)}
              >
                {allMatching
                  ? "Unselect all"
                  : query.variant_scope === "all"
                    ? `Select every printing of all ${result.total.toLocaleString()}`
                    : `Select all ${result.total.toLocaleString()}`}
              </Button>
            )}
            <div className="flex-1" />
            {/* Up here rather than in the filter panel: it changes what every tile offers, and
                "every Pikachu, every printing" is the master-collector question. */}
            <Segmented
              value={query.variant_scope ?? "canonical"}
              onChange={(v) => update({ scope: v === "all" ? ["all"] : [], variant: [] })}
              options={[
                { value: "canonical", label: "one per card" },
                { value: "all", label: "every printing" },
              ]}
            />
            <Select
              className="w-auto"
              value={sort}
              aria-label="Sort"
              onChange={(e) => update({ sort: [e.target.value] }, true)}
            >
              <option value="newest">Newest sets first</option>
              <option value="oldest">Oldest sets first</option>
              <option value="name">Name</option>
              <option value="price">Price, high to low</option>
            </Select>
          </div>

          {result && result.unplaceable_count > 0 && (
            <Callout>
              {result.unplaceable_count.toLocaleString()} more card
              {result.unplaceable_count === 1 ? "" : "s"} match but have no priced printing yet,
              so they cannot go in a goal or a binder. Ingesting prices for their sets picks them up.
            </Callout>
          )}
          {notice && <Callout tone="accent">{notice}</Callout>}
          {error && <Callout tone="danger">{(error as Error).message}</Callout>}

          {isLoading ? (
            <LoadingState label="Searching" />
          ) : !result || result.cards.length === 0 ? (
            <EmptyState title="No cards match">Loosen a filter or clear them all.</EmptyState>
          ) : (
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 md:grid-cols-4 xl:grid-cols-6">
              {result.cards.map((card) => {
                const ids = card.variants.map((v) => v.id);
                return (
                  <ResultTile
                    key={card.id}
                    card={card}
                    selected={allMatching ? new Set(ids) : selected}
                    showVariants={query.variant_scope === "all"}
                    onToggleCard={() => {
                      if (allMatching) return;
                      toggleVariants(ids, !ids.every((id) => selected.has(id)));
                    }}
                    onToggleVariant={(v) => {
                      if (allMatching) return;
                      toggleVariants([v.id], !selected.has(v.id));
                    }}
                  />
                );
              })}
            </div>
          )}

          {result && pageCount > 1 && (
            <div className="flex items-center justify-center gap-3">
              <Button
                variant="secondary"
                disabled={page === 0}
                onClick={() => update({ page: [String(page - 1)] }, true)}
              >
                &larr; Previous
              </Button>
              <span className="font-mono text-[12px] text-ink-3">
                page {page + 1} of {pageCount}
              </span>
              <Button
                variant="secondary"
                disabled={page + 1 >= pageCount}
                onClick={() => update({ page: [String(page + 1)] }, true)}
              >
                Next &rarr;
              </Button>
            </div>
          )}

          {/* Selection tray: sticky so it stays reachable while paging through results. */}
          <Panel className="sticky bottom-4 flex flex-col gap-3 p-4 shadow-lift">
            <div className="flex flex-wrap items-center gap-2">
              <SectionLabel>
                {hasSelection
                  ? `${selectionCount.toLocaleString()} selected${allMatching ? " (every match)" : ""}`
                  : "Nothing selected"}
              </SectionLabel>
              {selected.size > 0 && !allMatching && (
                <button
                  type="button"
                  className="font-mono text-[10.5px] text-ink-3 underline hover:text-ink"
                  onClick={() => setSelected(new Set())}
                >
                  clear
                </button>
              )}
            </div>

            {targetGoal ? (
              <div className="flex flex-wrap items-center gap-2.5">
                <Button disabled={!hasSelection || editGoal.isPending} onClick={addToGoal}>
                  {editGoal.isPending ? "Adding..." : `Add to ${targetGoal.name}`}
                </Button>
                <Link
                  to={`/goals/${targetGoal.id}`}
                  className="text-[12.5px] font-medium text-ink-3 hover:text-ink"
                >
                  Done
                </Link>
              </div>
            ) : (
              <div className="flex flex-col gap-3 xl:flex-row xl:items-end">
                <div className="flex flex-1 flex-wrap items-end gap-2.5">
                  <div className="min-w-[12rem] flex-1">
                    <Field label="New goal name">
                      <Input
                        value={goalName}
                        onChange={(e) => setGoalName(e.target.value)}
                        placeholder="Every Arita Charizard"
                      />
                    </Field>
                  </div>
                  <Button
                    disabled={!hasSelection || !goalName.trim() || createGoal.isPending}
                    onClick={saveAsList}
                    title="A fixed list of exactly these cards, which you can edit card by card."
                  >
                    Save selection as goal
                  </Button>
                  <Button
                    variant="secondary"
                    disabled={!describesAnything(query) || !goalName.trim() || createGoal.isPending}
                    onClick={saveAsLive}
                    title="Stores the filter itself: new sets that match are added when the goal is resynced. Ownership filters are ignored."
                  >
                    Save filter as live goal
                  </Button>
                </div>
                {customGoals.length > 0 && (
                  <div className="flex items-end gap-2.5">
                    <div className="w-48">
                      <Field label="Or add to">
                        <Select
                          value={addGoalId}
                          onChange={(e) =>
                            setAddGoalId(e.target.value ? Number(e.target.value) : "")
                          }
                        >
                          <option value="">Custom goal...</option>
                          {customGoals.map((g) => (
                            <option key={g.id} value={g.id}>
                              {g.name}
                            </option>
                          ))}
                        </Select>
                      </Field>
                    </div>
                    <Button
                      variant="secondary"
                      disabled={!hasSelection || addGoalId === "" || editGoal.isPending}
                      onClick={addToGoal}
                    >
                      Add
                    </Button>
                  </div>
                )}
              </div>
            )}
            {(createGoal.isError || editGoal.isError) && (
              <p className="text-[12px] text-danger-text">
                {((createGoal.error ?? editGoal.error) as Error).message}
              </p>
            )}
          </Panel>
        </div>
      </div>
    </Page>
  );
}
