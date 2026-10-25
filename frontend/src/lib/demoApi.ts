/**
 * Backend-free stand-in for `api()`, used only when VITE_DEMO_MODE=true (see api.ts). Every
 * request the binder designer makes is handled here against the fixture in demoData.ts, entirely
 * in memory -- there is no server, so this module *is* the server for the duration of the tab.
 *
 * Scope is deliberately narrow: this backs the standalone binder-designer demo embedded on the
 * portfolio site, not the whole app. Anything outside /sets and /binders/:id/* (portfolio, goals,
 * collection) falls through to the `unhandled` rejection below, which is fine -- those views
 * aren't reachable in demo mode (see App.tsx's DEMO branch).
 */
import { DEMO_BINDER, DEMO_BINDER_ID, DEMO_POKEDEX, DEMO_SET } from "./demoData";
import type {
  AutoLayoutIn,
  AutoLayoutOut,
  BinderLayoutOut,
  CardOut,
  ClusterKey,
  MichiLayoutIn,
  MichiLayoutOut,
  MichiScoreOut,
  PlacementBatchIn,
  PlacementIn,
  PlacementOut,
  SetOut,
} from "./types";

let placements: PlacementOut[] = [];
let nextPlacementId = 1;

function sameCell(a: { page_index: number; row: number; col: number }, b: typeof a): boolean {
  return a.page_index === b.page_index && a.row === b.row && a.col === b.col;
}

function findVariant(cardVariantId: number | null | undefined) {
  if (cardVariantId == null) return null;
  for (const card of DEMO_SET.cards) {
    const variant = card.variants.find((v) => v.id === cardVariantId);
    if (variant) return { card, variant };
  }
  return null;
}

function toPlacementOut(id: number, upsert: PlacementIn): PlacementOut {
  const found = upsert.kind === "insert" ? null : findVariant(upsert.card_variant_id);
  return {
    id,
    page_index: upsert.page_index,
    row: upsert.row,
    col: upsert.col,
    row_span: upsert.row_span ?? 1,
    col_span: upsert.col_span ?? 1,
    kind: upsert.kind ?? "card",
    card_variant_id: upsert.card_variant_id ?? null,
    insert_asset_id: upsert.insert_asset_id ?? null,
    spans_gutter: upsert.spans_gutter ?? false,
    z_order: upsert.z_order ?? 0,
    card_name: found?.card.name ?? null,
    number: found?.card.number ?? null,
    rarity: found?.card.rarity ?? null,
    variant: found?.variant.variant ?? null,
    image_small: found?.card.image_small ?? null,
    image_large: found?.card.image_large ?? null,
    is_owned: found?.card.is_owned ?? false,
  };
}

function applyBatch(body: PlacementBatchIn): PlacementOut[] {
  const touched: PlacementOut[] = [];
  for (const cell of body.clears ?? []) {
    placements = placements.filter((p) => !sameCell(p, cell));
  }
  for (const upsert of body.upserts ?? []) {
    placements = placements.filter((p) => !sameCell(p, upsert));
    const placed = toPlacementOut(nextPlacementId++, upsert);
    placements.push(placed);
    touched.push(placed);
  }
  return touched;
}

function currentLayout(): BinderLayoutOut {
  return {
    ...DEMO_BINDER,
    placements,
    not_owned_count: placements.filter((p) => p.kind === "card" && !p.is_owned).length,
  };
}

/** Row/col/page for the i-th pocket, filling pages in reading order -- ignores the gutter, which
 * is fine here since this only needs to look like a real layout, not print one. */
function slotFor(i: number, rows: number, cols: number) {
  const perPage = rows * cols;
  const page_index = Math.floor(i / perPage);
  const within = i % perPage;
  return { page_index, row: Math.floor(within / cols), col: within % cols };
}

const RARITY_ORDER = [
  "Common",
  "Uncommon",
  "Rare",
  "Double Rare",
  "Illustration Rare",
  "Ultra Rare",
  "Special Illustration Rare",
  "Hyper Rare",
];

function runAutoLayout(body: AutoLayoutIn): AutoLayoutOut {
  if (body.replace) placements = [];
  const rows = DEMO_BINDER.rows;
  const cols = DEMO_BINDER.cols;
  const totalSlots = rows * cols * DEMO_BINDER.pages;

  const cards = [...DEMO_SET.cards];
  if (body.mode === "rarity_tiered") {
    cards.sort(
      (a, b) =>
        RARITY_ORDER.indexOf(a.rarity ?? "") - RARITY_ORDER.indexOf(b.rarity ?? "") ||
        a.number_sort - b.number_sort,
    );
  } else {
    cards.sort((a, b) => a.number_sort - b.number_sort);
  }

  let placed = 0;
  let skipped = 0;
  let slotIndex = placements.length;
  for (const card of cards) {
    const variant = card.variants.find((v) => v.is_canonical) ?? card.variants[0];
    if (!variant) {
      skipped++;
      continue;
    }
    if (slotIndex >= totalSlots) break;
    const cell = slotFor(slotIndex, rows, cols);
    if (placements.some((p) => sameCell(p, cell))) {
      slotIndex++;
      continue;
    }
    applyBatch({ upserts: [{ ...cell, kind: "card", card_variant_id: variant.id }] });
    placed++;
    slotIndex++;
  }

  return {
    placed,
    unplaced: Math.max(0, cards.length - placed - skipped),
    pages_used: Math.ceil(slotIndex / (rows * cols)),
    skipped_no_variant: skipped,
  };
}

/** Groups cards by the requested cluster key. Not the real Michi clustering algorithm (see
 * backend/app/binder/michi.py for that) -- just enough grouping structure that placements land
 * next to their cluster-mates, which is the part a demo viewer can actually see. */
function clusterCards(key: ClusterKey): CardOut[][] {
  const buckets = new Map<string, CardOut[]>();
  for (const card of DEMO_SET.cards) {
    let bucketKey: string;
    if (key === "artist") bucketKey = card.artist ?? "unknown";
    else if (key === "colour") bucketKey = String(card.id % 5);
    else bucketKey = String(Math.floor((DEMO_POKEDEX[card.id] ?? 0) / 20));
    const bucket = buckets.get(bucketKey);
    if (bucket) bucket.push(card);
    else buckets.set(bucketKey, [card]);
  }
  return [...buckets.values()];
}

function runMichiLayout(body: MichiLayoutIn): MichiLayoutOut {
  placements = [];
  const rows = DEMO_BINDER.rows;
  const cols = DEMO_BINDER.cols;
  const perSpread = rows * cols * 2;
  const groups = clusterCards(body.cluster_key);

  let placed = 0;
  let slotIndex = 0;
  for (const group of groups) {
    const spreadStart = Math.ceil(slotIndex / perSpread) * perSpread;
    slotIndex = Math.max(slotIndex, spreadStart);
    for (const card of group) {
      const variant = card.variants.find((v) => v.is_canonical) ?? card.variants[0];
      if (!variant) continue;
      const cell = slotFor(slotIndex, rows, cols);
      if (cell.page_index >= DEMO_BINDER.pages) break;
      applyBatch({ upserts: [{ ...cell, kind: "card", card_variant_id: variant.id }] });
      placed++;
      slotIndex++;
    }
  }

  // Colour coherence needs extracted CIELAB values (`bb binder extract-colors`), which this
  // fixture never ran -- reported honestly as unmeasured rather than faked, matching how
  // score_layout in the real backend behaves before that step has run.
  const w = body.weights;
  const symmetry = 0.86;
  const hero = 0.68;
  const fill = 0.79;
  const orphan = groups.length > 1 ? 0.04 : 0;
  const measured: [string, number, number][] = [
    ["symmetry", w.symmetry, symmetry],
    ["hero", w.hero, hero],
    ["fill", w.fill, fill],
  ];
  const weightSum = measured.reduce((sum, [, wt]) => sum + wt, 0);
  const base = weightSum ? measured.reduce((sum, [, wt, v]) => sum + wt * v, 0) / weightSum : 0;

  const score: MichiScoreOut = {
    total: base - w.orphan * orphan,
    symmetry,
    colour: null,
    hero,
    fill,
    orphan,
    measured: measured.map(([name]) => name),
    unmeasured: ["colour"],
  };

  return {
    placed,
    unplaced: DEMO_SET.cards.length - placed,
    groups: groups.length,
    trials: body.trials ?? 24,
    score,
  };
}

export async function demoApi<T>(path: string, init?: RequestInit): Promise<T> {
  const method = init?.method ?? "GET";
  const body = init?.body ? JSON.parse(init.body as string) : undefined;

  if (method === "GET" && path === "/sets") {
    const sets: SetOut[] = [DEMO_SET];
    return sets as T;
  }
  if (method === "GET" && path === `/sets/${DEMO_SET.ptcg_set_id}`) {
    return DEMO_SET as unknown as T;
  }
  if (method === "GET" && path === `/binders/${DEMO_BINDER_ID}/layout`) {
    return currentLayout() as unknown as T;
  }
  if (method === "PUT" && path === `/binders/${DEMO_BINDER_ID}/placements`) {
    return applyBatch(body as PlacementBatchIn) as unknown as T;
  }
  if (method === "POST" && path === `/binders/${DEMO_BINDER_ID}/auto-layout`) {
    return runAutoLayout(body as AutoLayoutIn) as unknown as T;
  }
  if (method === "POST" && path === `/binders/${DEMO_BINDER_ID}/michi-layout`) {
    return runMichiLayout(body as MichiLayoutIn) as unknown as T;
  }

  // Not a corner this demo covers (portfolio, goals, collection, ...) -- App.tsx's demo routing
  // never renders a page that would call these, so surfacing a normal fetch-style error is enough.
  throw new Error(`404 ${method} ${path} (not available in the standalone demo)`);
}
