import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { api } from "../lib/api";
import { useSetDetail } from "../lib/queries";
import type { CardOut, CollectionItemIn, CollectionItemOut } from "../lib/types";
import { ErrorState, LoadingState } from "../components/ui";

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
    api<CollectionItemOut>("/collection/items", {
      method: "PUT",
      body: JSON.stringify(body),
    }).catch((err) => console.error("Failed to save collection item", err));
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

  if (isLoading) return <LoadingState />;
  if (error) return <ErrorState message={`Failed to load set: ${String(error)}`} />;
  if (!set || cards.length === 0) return <ErrorState message="No cards in this set." />;

  const enteredCount = cards.filter((c) =>
    c.variants.some((v) => v.is_canonical && (quantities.get(v.id) ?? 0) > 0),
  ).length;

  const canonicalQty = canonicalVariant ? (quantities.get(canonicalVariant.id) ?? 0) : undefined;
  const reverseQty = reverseVariant ? (quantities.get(reverseVariant.id) ?? 0) : undefined;

  return (
    <div className="min-h-screen select-none bg-canvas bg-glow">
      <div className="mx-auto flex max-w-5xl flex-col gap-4 px-6 py-6">
        {/* ------------------------------------------------------------- header */}
        <div className="flex items-center gap-4">
          <button
            onClick={leaveAndSync}
            className="text-[12.5px] font-medium text-ink-3 transition-colors hover:text-ink"
          >
            &larr; Back to grid (Esc)
          </button>
          <div className="flex-1" />
          <span className="font-mono text-[12.5px] text-ink-3">
            {index + 1} / {cards.length} · {enteredCount} entered
          </span>
        </div>

        <div className="h-1.5 overflow-hidden rounded-full bg-track">
          <div
            className="h-full bg-accent transition-[width]"
            style={{ width: `${((index + 1) / cards.length) * 100}%` }}
          />
        </div>

        {/* ------------------------------------------------------- card + controls */}
        <div className="flex flex-col gap-6 pt-2 sm:flex-row sm:gap-7">
          <div className="w-full max-w-[230px] flex-none">
            {card.image_large || card.image_small ? (
              <img
                src={card.image_large ?? card.image_small ?? undefined}
                alt={card.name}
                className="aspect-card w-full rounded-[9px] bg-well object-cover shadow-hero"
              />
            ) : (
              <div className="hatch-lg flex aspect-card w-full flex-col justify-end rounded-[9px] border border-line-card p-3 shadow-hero">
                <span className="font-mono text-[10px] uppercase tracking-[0.06em] text-ink-3">
                  No image
                </span>
                <span className="text-[15px] font-semibold text-ink">{card.name}</span>
              </div>
            )}
          </div>

          <div className="flex flex-1 flex-col gap-5 pt-1">
            <div className="flex flex-col gap-1">
              <h1 className="text-[24px] font-semibold tracking-[-0.4px] text-ink">
                <span className="font-mono text-accent-text">#{card.number}</span> {card.name}
              </h1>
              <p className="text-[13px] text-ink-3">
                {card.rarity ?? "Unknown rarity"} · {set.name}
              </p>
            </div>

            <div className="flex flex-wrap gap-3">
              <VariantTile
                label="Normal"
                active={activeKind === "canonical"}
                quantity={canonicalQty}
                onClick={() => setActiveKind("canonical")}
              />
              <VariantTile
                label="Reverse Holo"
                active={activeKind === "reverse"}
                quantity={reverseQty}
                unavailable={!reverseVariant}
                onClick={() => setActiveKind("reverse")}
              />
            </div>

            {flash && <p className="text-[12.5px] font-medium text-warn-text">{flash}</p>}

            <div className="flex flex-col gap-2.5">
              <span className="label-mono">Set quantity &amp; advance</span>
              <div className="flex flex-wrap gap-1.5">
                {Array.from({ length: 10 }, (_, d) => (
                  <button
                    key={d}
                    onClick={() => setQuantity(d)}
                    className="h-11 w-11 rounded-lg border border-line-strong bg-raised font-mono text-[15px] font-medium text-ink transition-colors hover:border-accent hover:text-accent-text"
                  >
                    {d}
                  </button>
                ))}
              </div>
              <div className="flex flex-wrap gap-1.5">
                <KeyButton onClick={() => goTo(index - 1)}>&larr; PREV</KeyButton>
                <KeyButton onClick={() => goTo(index + 1)}>NEXT &rarr;</KeyButton>
                <KeyButton
                  onClick={() => setActiveKind((k) => (k === "canonical" ? "reverse" : "canonical"))}
                >
                  R · TOGGLE REVERSE
                </KeyButton>
              </div>
            </div>
          </div>
        </div>

        {/* --------------------------------------------------------- set-order strip */}
        <div className="flex flex-col gap-2 pt-2">
          <span className="label-mono">Set order</span>
          <SetOrderStrip
            cards={cards}
            index={index}
            quantities={quantities}
            onPick={(i) => goTo(i)}
          />
          <span className="text-[11.5px] text-ink-3">
            Quantities save in the background — the set and portfolio refresh once, on the way out.
          </span>
        </div>
      </div>
    </div>
  );
}

function VariantTile({
  label,
  active,
  quantity,
  unavailable,
  onClick,
}: {
  label: string;
  active: boolean;
  quantity?: number;
  unavailable?: boolean;
  onClick: () => void;
}) {
  const base =
    "flex min-w-[118px] flex-col items-center gap-0.5 rounded-[9px] px-3.5 py-2.5 transition-colors";

  if (unavailable) {
    return (
      <div className={`${base} border border-dashed border-line-strong bg-inset`}>
        <span className="text-[11.5px] font-medium text-ink-4">{label}</span>
        <span className="font-mono text-[22px] font-bold text-ink-4">—</span>
      </div>
    );
  }

  return (
    <button
      onClick={onClick}
      className={`${base} ${
        active
          ? "border border-accent bg-accent-surface"
          : "border border-line-strong bg-raised hover:border-line-card"
      }`}
    >
      <span
        className={`text-[11.5px] font-medium ${active ? "text-accent-text" : "text-ink-3"}`}
      >
        {label}
      </span>
      <span className={`font-mono text-[22px] font-bold ${active ? "text-ink" : "text-ink-2"}`}>
        {quantity ?? 0}
      </span>
    </button>
  );
}

function KeyButton({ onClick, children }: { onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className="rounded-lg border border-line-strong bg-raised px-3.5 py-2.5 font-mono text-[12.5px] font-medium text-ink-2 transition-colors hover:border-accent hover:text-accent-text"
    >
      {children}
    </button>
  );
}

/** A sliding window of the set in number order: owned, empty, and the card in hand. */
function SetOrderStrip({
  cards,
  index,
  quantities,
  onPick,
}: {
  cards: CardOut[];
  index: number;
  quantities: Map<number, number>;
  onPick: (index: number) => void;
}) {
  const WINDOW = 12;
  const start = Math.max(0, Math.min(cards.length - WINDOW, index - Math.floor(WINDOW / 2)));
  const visible = cards.slice(start, start + WINDOW);

  return (
    <div className="flex gap-1.5 overflow-x-auto pb-1">
      {visible.map((c, i) => {
        const realIndex = start + i;
        const active = realIndex === index;
        const owned = c.variants.some((v) => (quantities.get(v.id) ?? 0) > 0);
        return (
          <button
            key={c.id}
            onClick={() => onPick(realIndex)}
            title={`#${c.number} ${c.name}`}
            className={`flex aspect-card w-[58px] flex-none items-end rounded-[5px] p-1 transition-colors ${
              active
                ? "hatch border-2 border-accent shadow-glow"
                : owned
                  ? "border border-accent-line bg-accent-surface"
                  : "border border-dashed border-line-strong bg-raised"
            }`}
          >
            <span
              className={`font-mono text-[9.5px] font-medium ${
                active || owned ? "text-accent-text" : "text-ink-4"
              }`}
            >
              {c.number}
            </span>
          </button>
        );
      })}
    </div>
  );
}
