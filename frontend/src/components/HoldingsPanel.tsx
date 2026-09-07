import { useEffect, useMemo, useState } from "react";
import type { HoldingGroupKey, HoldingOut } from "../lib/types";
import { formatMoney, parseMoney } from "../lib/types";
import { CardTileBase } from "./CardTile";
import { Chip, Input, Segmented, Select, Table, Tag, Td, Th, Tr } from "./ui";

/**
 * The owned cards: sort, filter, and find where a card physically is, as a table or a card grid.
 *
 * Both views render the same filtered, sorted rows -- the view switch is presentation only, so a
 * filter set up in one carries into the other.
 *
 * Sorting and filtering are client-side over the whole collection. At a few thousand rows that
 * is instant and avoids a request per keystroke; the backend hands over the full list for
 * exactly this reason (see services/portfolio.list_holdings).
 *
 * Grouping is the exception -- it is a server concern, because it decides what a row's quantity
 * and value actually mean. The chips here change the request, not the rendering.
 */

/** Label and explanation per groupable field. Order is the order the chips appear in. */
const GROUP_OPTIONS: { key: HoldingGroupKey; label: string; hint: string }[] = [
  { key: "condition", label: "condition", hint: "An NM and a LP copy are separate holdings" },
  { key: "language", label: "language", hint: "An English and a Japanese copy are separate" },
  { key: "graded", label: "graded", hint: "A slabbed copy is separate from a raw one" },
  { key: "grade", label: "grade", hint: "A PSA 10 is separate from a PSA 9" },
  { key: "location", label: "location", hint: "One row per physical slot -- every copy listed" },
];

// Row caps. The table is cheap per row; a grid tile is an image request, so it stops sooner.
const TABLE_CAP = 500;
const GRID_CAP = 120;

type View = "grid" | "table";

const VIEW_STORAGE_KEY = "bb.holdings.view";

/** Remembering the view is a per-user habit, not app state -- localStorage, not the server.
 * Both accessors are guarded: a private window or blocked site data makes them throw, and a
 * holdings list that cannot render because of a remembered preference would be a poor trade. */
function useStoredView(): [View, (v: View) => void] {
  const [view, setView] = useState<View>(() => {
    try {
      return localStorage.getItem(VIEW_STORAGE_KEY) === "grid" ? "grid" : "table";
    } catch {
      return "table";
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(VIEW_STORAGE_KEY, view);
    } catch {
      /* not worth surfacing: the view still works, it just will not be remembered. */
    }
  }, [view]);
  return [view, setView];
}

type SortKey = "set" | "number" | "name" | "rarity" | "condition" | "quantity" | "value" | "location";

const SORT_LABELS: Record<SortKey, string> = {
  set: "Set",
  number: "#",
  name: "Card",
  rarity: "Rarity",
  condition: "Cond",
  quantity: "Qty",
  value: "Value",
  location: "Location",
};

/** Sort value for a column. Money and numbers compare numerically, everything else as text. */
function sortValue(h: HoldingOut, key: SortKey): string | number {
  switch (key) {
    case "set":
      return h.set_name.toLowerCase();
    case "number":
      return h.number_sort;
    case "name":
      return h.name.toLowerCase();
    case "rarity":
      return (h.rarity ?? "").toLowerCase();
    case "condition":
      return h.condition;
    case "quantity":
      return h.quantity;
    case "value":
      return parseMoney(h.market_value) ?? -1;
    case "location":
      // A group spread across several slots sorts by its first, so it lands near its siblings.
      // Unlocated cards sort last in either direction rather than clumping at the top.
      return h.storage_location ?? h.locations[0] ?? "￿";
  }
}

function SortHeader({
  column,
  sort,
  dir,
  onSort,
  className,
}: {
  column: SortKey;
  sort: SortKey;
  dir: "asc" | "desc";
  onSort: (k: SortKey) => void;
  className?: string;
}) {
  const active = sort === column;
  return (
    <Th className={className}>
      <button
        type="button"
        onClick={() => onSort(column)}
        aria-label={`Sort by ${SORT_LABELS[column]}`}
        className={`inline-flex items-center gap-1 uppercase tracking-[0.08em] transition-colors hover:text-ink ${
          active ? "text-ink" : ""
        }`}
      >
        {SORT_LABELS[column]}
        <span aria-hidden="true" className={active ? "text-accent-text" : "text-ink-4"}>
          {active ? (dir === "asc" ? "↑" : "↓") : "↕"}
        </span>
      </button>
    </Th>
  );
}

/** The same rows as tiles. Location goes on the face of the tile rather than behind a hover,
 * because "where is this card?" is the question the grid is worst at answering otherwise. */
function HoldingsGrid({ holdings }: { holdings: HoldingOut[] }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 xl:grid-cols-7">
      {holdings.map((h) => (
        <CardTileBase
          key={h.item_id}
          name={h.name}
          number={h.number}
          rarity={h.rarity}
          imageSmall={h.image_small}
          price={h.market_value}
          owned
          variantLabel={h.variant === "normal" ? undefined : h.variant.replace(/_/g, " ")}
          quantity={h.quantity}
          condition={h.condition}
          location={
            h.storage_location ?? (h.locations.length > 1 ? `${h.locations.length} locations` : null)
          }
        />
      ))}
    </div>
  );
}

export default function HoldingsPanel({
  holdings,
  groupBy,
  onGroupByChange,
}: {
  holdings: HoldingOut[];
  groupBy: HoldingGroupKey[];
  onGroupByChange: (keys: HoldingGroupKey[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [setFilter, setSetFilter] = useState("");
  const [rarityFilter, setRarityFilter] = useState("");
  const [conditionFilter, setConditionFilter] = useState("");
  const [ownedOnly, setOwnedOnly] = useState(true);
  const [view, setView] = useStoredView();
  const [sort, setSort] = useState<SortKey>("set");
  const [dir, setDir] = useState<"asc" | "desc">("asc");

  const sets = useMemo(
    () => [...new Set(holdings.map((h) => h.set_name))].sort((a, b) => a.localeCompare(b)),
    [holdings],
  );
  const rarities = useMemo(
    () =>
      [...new Set(holdings.map((h) => h.rarity).filter((r): r is string => !!r))].sort((a, b) =>
        a.localeCompare(b),
      ),
    [holdings],
  );
  const conditions = useMemo(
    () => [...new Set(holdings.map((h) => h.condition))].sort(),
    [holdings],
  );

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = holdings.filter((h) => {
      if (ownedOnly && h.quantity < 1) return false;
      if (setFilter && h.set_name !== setFilter) return false;
      if (rarityFilter && h.rarity !== rarityFilter) return false;
      if (conditionFilter && h.condition !== conditionFilter) return false;
      if (!q) return true;
      return (
        h.name.toLowerCase().includes(q) ||
        h.number.toLowerCase().includes(q) ||
        h.set_name.toLowerCase().includes(q) ||
        (h.storage_location ?? "").toLowerCase().includes(q)
      );
    });
    const sign = dir === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const av = sortValue(a, sort);
      const bv = sortValue(b, sort);
      if (av < bv) return -1 * sign;
      if (av > bv) return 1 * sign;
      // Stable, predictable tiebreak so equal keys never shuffle between renders.
      return a.set_name.localeCompare(b.set_name) || a.number_sort - b.number_sort;
    });
  }, [holdings, query, setFilter, rarityFilter, conditionFilter, ownedOnly, sort, dir]);

  const shownValue = rows.reduce((sum, h) => sum + (parseMoney(h.market_value) ?? 0), 0);
  const shownCards = rows.reduce((sum, h) => sum + h.quantity, 0);
  const located = rows.filter((h) => h.storage_location || h.locations.length > 0).length;
  const multiCopy = rows.filter((h) => h.copies > 1).length;

  function handleSort(key: SortKey) {
    if (key === sort) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSort(key);
      // Value and quantity are most useful highest-first; text columns A-Z.
      setDir(key === "value" || key === "quantity" ? "desc" : "asc");
    }
  }

  /** Header clicks toggle direction on re-click; picking from the grid's dropdown should not. */
  function selectSort(key: SortKey) {
    setSort(key);
    setDir(key === "value" || key === "quantity" ? "desc" : "asc");
  }

  function reset() {
    setQuery("");
    setSetFilter("");
    setRarityFilter("");
    setConditionFilter("");
    setOwnedOnly(true);
  }

  const cap = view === "grid" ? GRID_CAP : TABLE_CAP;

  const filtersActive =
    !!query || !!setFilter || !!rarityFilter || !!conditionFilter || !ownedOnly;

  function toggleGroup(key: HoldingGroupKey) {
    onGroupByChange(
      groupBy.includes(key) ? groupBy.filter((k) => k !== key) : [...groupBy, key],
    );
  }

  const expanded = groupBy.includes("location");

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-3">
          A holding is one card, plus:
        </span>
        {GROUP_OPTIONS.map((opt) => (
          <Chip
            key={opt.key}
            active={groupBy.includes(opt.key)}
            onClick={() => toggleGroup(opt.key)}
            title={opt.hint}
          >
            {opt.label}
          </Chip>
        ))}
        <Segmented<View>
          className="ml-auto"
          value={view}
          onChange={setView}
          options={[
            { value: "table", label: "TABLE" },
            { value: "grid", label: "GRID" },
          ]}
        />
      </div>

      <div className="flex flex-wrap items-end gap-2.5">
        <div className="min-w-[200px] flex-1">
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search name, number, set, or location..."
            aria-label="Search holdings"
          />
        </div>
        {/* !w-auto: Select hardcodes w-full and cx is a plain join, so without the important
            prefix the base wins on CSS order and every filter stacks full-width. */}
        <Select
          value={setFilter}
          onChange={(e) => setSetFilter(e.target.value)}
          aria-label="Filter by set"
          className="!w-auto min-w-[150px]"
        >
          <option value="">All sets</option>
          {sets.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </Select>
        <Select
          value={rarityFilter}
          onChange={(e) => setRarityFilter(e.target.value)}
          aria-label="Filter by rarity"
          className="!w-auto min-w-[130px]"
        >
          <option value="">All rarities</option>
          {rarities.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </Select>
        <Select
          value={conditionFilter}
          onChange={(e) => setConditionFilter(e.target.value)}
          aria-label="Filter by condition"
          className="!w-auto min-w-[110px]"
        >
          <option value="">All conditions</option>
          {conditions.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </Select>
        <Chip active={ownedOnly} onClick={() => setOwnedOnly((v) => !v)}>
          owned only
        </Chip>
        {filtersActive && (
          <Chip tone="neutral" onClick={reset}>
            clear
          </Chip>
        )}
      </div>

      <div className="flex flex-wrap items-baseline gap-x-4 font-mono text-[11px] text-ink-3">
        <span>
          {rows.length.toLocaleString()} of {holdings.length.toLocaleString()} rows
        </span>
        <span>{shownCards.toLocaleString()} cards</span>
        <span>
          <span className="text-ink">{formatMoney(String(shownValue.toFixed(2)))}</span> shown
        </span>
        {located === 0 ? (
          <span className="text-warn-text">no storage locations recorded</span>
        ) : (
          <span>{located.toLocaleString()} located</span>
        )}
        {!expanded && multiCopy > 0 && (
          <span className="text-ink-3">
            {multiCopy.toLocaleString()} {multiCopy === 1 ? "row holds" : "rows hold"} more than one
            copy — add <span className="text-ink">location</span> to list them separately
          </span>
        )}
      </div>

      {view === "grid" && (
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-3">
            Sort
          </span>
          <Select
            value={sort}
            onChange={(e) => selectSort(e.target.value as SortKey)}
            aria-label="Sort holdings"
            className="!w-auto min-w-[130px]"
          >
            {(Object.keys(SORT_LABELS) as SortKey[]).map((k) => (
              <option key={k} value={k}>
                {SORT_LABELS[k]}
              </option>
            ))}
          </Select>
          <Chip
            tone="neutral"
            onClick={() => setDir((d) => (d === "asc" ? "desc" : "asc"))}
            title={dir === "asc" ? "Ascending" : "Descending"}
          >
            {dir === "asc" ? "↑ asc" : "↓ desc"}
          </Chip>
        </div>
      )}

      {view === "grid" ? (
        <HoldingsGrid holdings={rows.slice(0, GRID_CAP)} />
      ) : (
      <Table
        head={
          <>
            <SortHeader column="set" sort={sort} dir={dir} onSort={handleSort} />
            <SortHeader column="number" sort={sort} dir={dir} onSort={handleSort} className="w-16" />
            <SortHeader column="name" sort={sort} dir={dir} onSort={handleSort} />
            <SortHeader column="rarity" sort={sort} dir={dir} onSort={handleSort} />
            <SortHeader
              column="condition"
              sort={sort}
              dir={dir}
              onSort={handleSort}
              className="w-16"
            />
            <SortHeader
              column="quantity"
              sort={sort}
              dir={dir}
              onSort={handleSort}
              className="w-14"
            />
            <SortHeader column="value" sort={sort} dir={dir} onSort={handleSort} className="w-24" />
            <SortHeader column="location" sort={sort} dir={dir} onSort={handleSort} />
          </>
        }
      >
        {rows.length === 0 ? (
          <Tr>
            <Td colSpan={8} className="py-10 text-center text-ink-3">
              No holdings match these filters.
            </Td>
          </Tr>
        ) : (
          rows.slice(0, TABLE_CAP).map((h) => (
            <Tr key={h.item_id}>
              <Td className="text-[12px] text-ink-3">{h.set_name}</Td>
              <Td className="font-mono text-[11.5px] text-accent-text">{h.number}</Td>
              <Td>
                <div className="flex items-center gap-2">
                  <span className="text-ink">{h.name}</span>
                  {h.variant !== "normal" && <Tag tone="neutral">{h.variant.replace(/_/g, " ")}</Tag>}
                  {h.is_graded && <Tag tone="accent">{h.grade ?? "graded"}</Tag>}
                </div>
              </Td>
              <Td className="text-[12px] text-ink-3">{h.rarity ?? "—"}</Td>
              <Td className="font-mono text-[11.5px]">{h.condition}</Td>
              <Td className="font-mono text-[11.5px]">{h.quantity}</Td>
              <Td className="text-right font-mono text-[11.5px]">{formatMoney(h.market_value)}</Td>
              {/* nowrap: a slot label is meaningless broken across lines. Table scrolls. */}
              <Td className="whitespace-nowrap font-mono text-[11.5px]">
                {h.storage_location ? (
                  h.storage_location
                ) : h.locations.length > 0 ? (
                  // Collapsed across slots: name the count and keep the full list one hover away,
                  // rather than picking one slot and quietly implying the others do not exist.
                  <span
                    title={h.locations.join(", ")}
                    className="cursor-help border-b border-dotted border-ink-4"
                  >
                    {h.locations.length} locations
                  </span>
                ) : (
                  <span className="text-ink-4">—</span>
                )}
              </Td>
            </Tr>
          ))
        )}
      </Table>
      )}

      {rows.length > cap && (
        <p className="text-[11.5px] text-ink-3">
          Showing the first {cap.toLocaleString()} of {rows.length.toLocaleString()} matching rows
          — narrow the filters to see the rest.
        </p>
      )}
    </div>
  );
}
