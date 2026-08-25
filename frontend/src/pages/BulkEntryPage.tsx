import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useSetDetail } from "../lib/queries";
import type { CollectionItemIn, CollectionItemOut } from "../lib/types";

/**
 * Fast bulk entry (PRD T4 / roadmap 1.10): walk a set in number order, digit keys 0-9 set the
 * active variant's quantity and auto-advance, arrows navigate manually, 'r' toggles the active
 * variant between the canonical print and reverse holofoil.
 *
 * Speed is the entire point (CLAUDE.md: "if entering 200 cards takes more than five minutes, it
 * is not done"), so quantity edits update local state instantly and PUT in the background --
 * they do NOT wait for the server or refetch the set on every keystroke. The set/portfolio
 * queries are only invalidated once, on the way out.
 */
export default function BulkEntryPage() {
  const { ptcgSetId } = useParams<{ ptcgSetId: string }>();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: set, isLoading, error } = useSetDetail(ptcgSetId);

  const [index, setIndex] = useState(0);
  const [activeKind, setActiveKind] = useState<"canonical" | "reverse">("canonical");
  // variantId -> quantity, seeded from the fetched set and updated optimistically as we go.
  const [quantities, setQuantities] = useState<Map<number, number>>(new Map());
  const [flash, setFlash] = useState<string | null>(null);

  useEffect(() => {
    if (!set) return;
    const initial = new Map<number, number>();
    for (const card of set.cards) {
      for (const v of card.variants) initial.set(v.id, v.owned_quantity);
    }
    setQuantities(initial);
  }, [set]);

  const cards = set?.cards ?? [];
  const card = cards[index];

  const canonicalVariant = useMemo(
    () => card?.variants.find((v) => v.is_canonical) ?? card?.variants[0],
    [card],
  );
  const reverseVariant = useMemo(
    () => card?.variants.find((v) => v.tcgplayer_sub_type_name === "Reverse Holofoil"),
    [card],
  );
  const activeVariant = activeKind === "reverse" ? reverseVariant : canonicalVariant;

  // Cheap fire-and-forget upsert -- no react-query mutation wrapper, deliberately no
  // invalidation per keystroke (see the module docstring for why).
  const save = useCallback((body: CollectionItemIn) => {
    api<CollectionItemOut>("/collection/items", { method: "PUT", body: JSON.stringify(body) }).catch(
      (err) => console.error("Failed to save collection item", err),
    );
  }, []);

  const goTo = useCallback(
    (next: number) => {
      if (cards.length === 0) return;
      setIndex(Math.max(0, Math.min(cards.length - 1, next)));
    },
    [cards.length],
  );

  const setQuantity = useCallback(
    (digit: number) => {
      if (!activeVariant) {
        setFlash(
          activeKind === "reverse"
            ? "This card has no reverse holofoil printing"
            : "This card has no variant to set",
        );
        setTimeout(() => setFlash(null), 900);
        return;
      }
      setQuantities((prev) => {
        const next = new Map(prev);
        next.set(activeVariant.id, digit);
        return next;
      });
      save({ card_variant_id: activeVariant.id, quantity: digit });
      goTo(index + 1);
    },
    [activeVariant, activeKind, save, goTo, index],
  );

  const leaveAndSync = useCallback(() => {
    if (ptcgSetId) void queryClient.invalidateQueries({ queryKey: ["sets", ptcgSetId] });
    void queryClient.invalidateQueries({ queryKey: ["portfolio"] });
    navigate(`/sets/${ptcgSetId}`);
  }, [ptcgSetId, queryClient, navigate]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key >= "0" && e.key <= "9") {
        e.preventDefault();
        setQuantity(Number(e.key));
        return;
      }
      switch (e.key) {
        case "ArrowRight":
        case "ArrowDown":
          e.preventDefault();
          goTo(index + 1);
          break;
        case "ArrowLeft":
        case "ArrowUp":
          e.preventDefault();
          goTo(index - 1);
          break;
        case "r":
        case "R":
          e.preventDefault();
          setActiveKind((k) => (k === "canonical" ? "reverse" : "canonical"));
          break;
        case "Escape":
          e.preventDefault();
          leaveAndSync();
          break;
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [index, goTo, setQuantity, leaveAndSync]);

  if (isLoading) return <p className="p-6 text-neutral-500">Loading...</p>;
  if (error) return <p className="p-6 text-red-600">Failed to load set: {String(error)}</p>;
  if (!set || cards.length === 0) return <p className="p-6 text-neutral-500">No cards in this set.</p>;

  const enteredCount = cards.filter((c) =>
    c.variants.some((v) => v.is_canonical && (quantities.get(v.id) ?? 0) > 0),
  ).length;

  return (
    <div className="mx-auto flex max-w-2xl flex-col items-center p-6 select-none">
      <div className="mb-4 flex w-full items-center justify-between">
        <Link to={`/sets/${set.ptcg_set_id}`} onClick={(e) => { e.preventDefault(); leaveAndSync(); }} className="text-sm text-neutral-500 hover:text-neutral-800">
          ← Back to grid (Esc)
        </Link>
        <div className="text-sm text-neutral-500">
          {index + 1} / {cards.length} · {enteredCount} entered
        </div>
      </div>

      <div className="w-full overflow-hidden rounded-lg bg-neutral-100">
        <div
          className="h-1.5 bg-emerald-500 transition-all"
          style={{ width: `${((index + 1) / cards.length) * 100}%` }}
        />
      </div>

      <div className="mt-6 flex flex-col items-center">
        {card.image_large || card.image_small ? (
          <img
            src={card.image_large ?? card.image_small ?? undefined}
            alt={card.name}
            className="h-96 w-72 rounded-lg bg-neutral-200 object-cover shadow-md"
          />
        ) : (
          <div className="flex h-96 w-72 items-center justify-center rounded-lg bg-neutral-200 text-neutral-500">
            {card.name}
          </div>
        )}

        <h2 className="mt-4 text-xl font-semibold">
          #{card.number} {card.name}
        </h2>
        <p className="text-sm text-neutral-500">{card.rarity}</p>

        <div className="mt-4 flex gap-3">
          <VariantBadge
            label="Normal"
            active={activeKind === "canonical"}
            quantity={canonicalVariant ? (quantities.get(canonicalVariant.id) ?? 0) : undefined}
          />
          <VariantBadge
            label="Reverse Holo"
            active={activeKind === "reverse"}
            quantity={reverseVariant ? (quantities.get(reverseVariant.id) ?? 0) : undefined}
            unavailable={!reverseVariant}
          />
        </div>

        {flash && <p className="mt-3 text-sm text-amber-600">{flash}</p>}

        <p className="mt-8 text-xs text-neutral-400">
          Press <kbd className="rounded border px-1">0</kbd>–<kbd className="rounded border px-1">9</kbd>{" "}
          to set quantity and advance · <kbd className="rounded border px-1">←</kbd>/
          <kbd className="rounded border px-1">→</kbd> to navigate ·{" "}
          <kbd className="rounded border px-1">r</kbd> toggles reverse holo
        </p>
      </div>
    </div>
  );
}

function VariantBadge({
  label,
  active,
  quantity,
  unavailable,
}: {
  label: string;
  active: boolean;
  quantity?: number;
  unavailable?: boolean;
}) {
  return (
    <div
      className={`flex min-w-[6rem] flex-col items-center rounded-md border px-3 py-2 ${
        unavailable
          ? "border-neutral-100 text-neutral-300"
          : active
            ? "border-emerald-500 bg-emerald-50"
            : "border-neutral-200"
      }`}
    >
      <span className="text-xs font-medium">{label}</span>
      <span className="text-lg font-semibold">{unavailable ? "—" : (quantity ?? 0)}</span>
    </div>
  );
}
