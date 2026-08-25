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

export function parseMoney(value: string | null): number | null {
  if (value === null) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function formatMoney(value: string | null): string {
  const n = parseMoney(value);
  return n === null ? "—" : `$${n.toFixed(2)}`;
}
