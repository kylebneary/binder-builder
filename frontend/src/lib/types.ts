// Mirrors backend/app/api/schemas.py. Money fields are strings on the wire (Pydantic
// serializes Decimal as a string), parsed with parseMoney below rather than Number() directly.

export interface VariantOut {
  id: number;
  variant: string;
  tcgplayer_product_id: number | null;
  tcgplayer_sub_type_name: string | null;
  is_canonical: boolean;
  market_price: string | null;
  owned_quantity: number;
}

export interface CardOut {
  id: number;
  ptcg_card_id: string;
  number: string;
  number_sort: number;
  name: string;
  supertype: string | null;
  rarity: string | null;
  artist: string | null;
  image_small: string | null;
  image_large: string | null;
  variants: VariantOut[];
  is_owned: boolean;
}

export interface SetOut {
  id: number;
  ptcg_set_id: string;
  name: string;
  series: string | null;
  printed_total: number | null;
  total: number | null;
  release_date: string | null;
  symbol_url: string | null;
  logo_url: string | null;
}

export interface SetDetailOut extends SetOut {
  cards: CardOut[];
  owned_count: number;
  needed_count: number;
}

export interface CollectionItemIn {
  card_variant_id: number;
  quantity?: number;
  condition?: string;
  language?: string;
  is_graded?: boolean;
  grader?: string | null;
  grade?: string | null;
  acquired_price?: string | null;
  acquired_on?: string | null;
  storage_location?: string | null;
  notes?: string | null;
}

export interface CollectionItemOut {
  id: number;
  collection_id: number;
  card_variant_id: number;
  quantity: number;
  condition: string;
  language: string;
  is_graded: boolean;
  grader: string | null;
  grade: string | null;
  acquired_price: string | null;
  acquired_on: string | null;
  storage_location: string | null;
  notes: string | null;
}

export interface PortfolioSummaryOut {
  collection_id: number;
  total_market_value: string;
  total_cost_basis: string;
  unrealized_gain: string;
  item_count: number;
  priced_item_count: number;
  price_date: string | null;
}

export interface PortfolioValuePointOut {
  observed_on: string;
  total_market_value: string;
}

export interface GoalIn {
  name: string;
  goal_type: string;
  set_id?: number | null;
  filter_json?: Record<string, unknown> | null;
  target_condition?: string;
}

export interface GoalOut {
  id: number;
  name: string;
  goal_type: string;
  set_id: number | null;
  filter_json: Record<string, unknown> | null;
  target_condition: string;
}

export interface NeedItemOut {
  card_variant_id: number;
  card_name: string;
  number: string;
  rarity: string | null;
  variant: string;
  required_qty: number;
  owned_qty: number;
  need_qty: number;
  market_price: string | null;
}

export interface SinglesCostOut {
  n_cards: number;
  subtotal: string;
  orders: number;
  shipping: string;
  tax: string;
  total: string;
}

export interface GoalDetailOut {
  id: number;
  name: string;
  goal_type: string;
  set_id: number | null;
  target_condition: string;
  items: NeedItemOut[];
  cost: SinglesCostOut;
  unpriced_count: number;
}

export interface SealedProductOut {
  id: number;
  name: string;
  product_type: string;
  packs_per_unit: number | null;
  msrp: string | null;
  market_price: string | null;
  has_pull_rate_profile: boolean;
}

export type Objective =
  | "min_expected_cost"
  | "min_p90_cost"
  | "max_completion_under_budget"
  | "min_cost_for_target_completion";

export interface SimulateIn {
  objective?: Objective;
  n_trials?: number;
  seed?: number;
  sealed_product_ids?: number[] | null;
  shipping_per_order?: number;
  cards_per_order?: number;
  sealed_shipping?: number;
  sales_tax_rate?: number;
  liquidation_rate?: number;
  resale_floor?: number;
  bulk_threshold?: number;
}

export interface StrategyOut {
  units: Record<string, number>; // sealed_product_id (as string, JSON object key) -> qty
}

export interface SimResultOut {
  mean: number;
  sd: number;
  p10: number;
  p50: number;
  p90: number;
  p95: number;
  p_complete_from_sealed: number;
  expected_cards_remaining: number;
  n_trials: number;
  seed: number;
  histogram_counts: number[];
  histogram_edges: number[];
}

export interface RankedStrategyOut {
  simulation_run_id: number;
  strategy: StrategyOut;
  result: SimResultOut;
}

export interface UnsimulatableProductOut {
  sealed_product_id: number;
  name: string;
  reason: string;
}

export interface SimulateResponseOut {
  goal_id: number;
  objective: string;
  ranked: RankedStrategyOut[];
  unsimulatable: UnsimulatableProductOut[];
  uncovered_needed_price_sum: string;
}

export interface SensitivityIn {
  sealed_product_ids: Record<number, number>;
  n_trials?: number;
  seed?: number;
  shipping_per_order?: number;
  cards_per_order?: number;
  sealed_shipping?: number;
  sales_tax_rate?: number;
  liquidation_rate?: number;
  resale_floor?: number;
  bulk_threshold?: number;
}

export interface SensitivityFactorOut {
  name: string;
  baseline_cost: number;
  low_cost: number;
  high_cost: number;
}

export interface SensitivityOut {
  robust: boolean;
  baseline_mean: number;
  strategy_mean: number;
  factors: SensitivityFactorOut[];
}

export function parseMoney(value: string | null): number | null {
  if (value === null) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function formatMoney(value: string | null): string {
  const n = parseMoney(value);
  return n === null ? "—" : `$${n.toFixed(2)}`;
}

/* ------------------------------------------------------------------- binder */

export interface BinderIn {
  name: string;
  rows?: number;
  cols?: number;
  pages?: number;
  is_side_loading?: boolean;
  gutter_mm?: number;
  notes?: string | null;
}

export interface BinderOut {
  id: number;
  name: string;
  rows: number;
  cols: number;
  pages: number;
  is_side_loading: boolean;
  gutter_mm: number;
  notes: string | null;
}

export type PlacementKind = "card" | "insert" | "empty";

export interface PlacementIn {
  page_index: number;
  row: number;
  col: number;
  kind?: PlacementKind;
  row_span?: number;
  col_span?: number;
  card_variant_id?: number | null;
  insert_asset_id?: number | null;
  spans_gutter?: boolean;
  z_order?: number;
}

export interface PlacementCellIn {
  page_index: number;
  row: number;
  col: number;
}

export interface PlacementBatchIn {
  upserts?: PlacementIn[];
  clears?: PlacementCellIn[];
}

export interface PlacementOut {
  id: number;
  page_index: number;
  row: number;
  col: number;
  row_span: number;
  col_span: number;
  kind: PlacementKind;
  card_variant_id: number | null;
  insert_asset_id: number | null;
  spans_gutter: boolean;
  z_order: number;
  card_name: string | null;
  number: string | null;
  rarity: string | null;
  variant: string | null;
  image_small: string | null;
  image_large: string | null;
  is_owned: boolean;
}

export interface BinderLayoutOut extends BinderOut {
  placements: PlacementOut[];
  not_owned_count: number;
}

export interface AutoLayoutIn {
  set_id: number;
  mode?: "set_order" | "rarity_tiered";
  canonical_only?: boolean;
  skip_reverse_holos?: boolean;
  group_by_rarity?: boolean;
  start_subset_on_new_page?: boolean;
  replace?: boolean;
}

export interface AutoLayoutOut {
  placed: number;
  unplaced: number;
  pages_used: number;
  /** Cards in the set with no priced variant, so nothing could be placed for them at all. */
  skipped_no_variant: number;
}

/** One owned card, flattened for the holdings table. Mirrors HoldingOut. */
export interface HoldingOut {
  item_id: number;
  card_variant_id: number;
  card_id: number;
  ptcg_card_id: string;
  name: string;
  number: string;
  number_sort: number;
  set_id: number;
  set_name: string;
  ptcg_set_id: string;
  rarity: string | null;
  variant: string;
  condition: string;
  language: string;
  quantity: number;
  is_graded: boolean;
  grade: string | null;
  storage_location: string | null;
  acquired_price: string | null;
  market_price: string | null;
  market_value: string | null;
  image_small: string | null;
}
