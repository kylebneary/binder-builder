// Collector-facing names for the variant enum. Anything new from the price feed falls back to
// its enum value with spaces; tagged printings carry their label from the server
// (data/printing_tags.yaml).
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
  // The placeholder for a card whose printings the price feed hasn't told us yet; its price slot
  // reads "Unpriced" like any other printing without a price.
  unpriced: "Printing unknown",
};

export function variantLabel(v: string, label?: string | null): string {
  return label ?? VARIANT_LABELS[v] ?? v.replace(/_/g, " ");
}
