import {
  DndContext,
  DragOverlay,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  pointerWithin,
  useDraggable,
  useSensor,
  useSensors,
  type CollisionDetection,
  type DragEndEvent,
  type DragStartEvent,
} from "@dnd-kit/core";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import type { ClusterKey, MichiWeights } from "../lib/types";
import { DEFAULT_MICHI_WEIGHTS } from "../lib/types";
import { PlacedCard, parsePocketId } from "../components/BinderPocket";
import BinderContents from "../components/BinderContents";
import SpreadView from "../components/SpreadView";
import {
  Button,
  Callout,
  Chip,
  ErrorState,
  Field,
  LoadingState,
  Page,
  PageHeader,
  Panel,
  SectionLabel,
  Segmented,
  Select,
  Tag,
} from "../components/ui";
import {
  useAutoLayout,
  useMichiLayout,
  useBinderLayout,
  useSetPlacements,
  useSetDetail,
  useSets,
} from "../lib/queries";
import type { CardOut, PlacementBatchIn, PlacementOut } from "../lib/types";

/**
 * The binder editor.
 *
 * Every edit is expressed as a pair of batches -- the gesture and its exact inverse -- which is
 * what makes undo/redo a replay of ordinary placement calls rather than a special server
 * feature. The stack lives here in component state on purpose: it is scoped to this editing
 * session, and reaching for a state-management library to hold two arrays would be overkill.
 */

interface Edit {
  apply: PlacementBatchIn;
  invert: PlacementBatchIn;
}

/** A placement expressed as the upsert that would recreate it. */
function asUpsert(p: PlacementOut, at?: { page_index: number; row: number; col: number }) {
  return {
    page_index: at?.page_index ?? p.page_index,
    row: at?.row ?? p.row,
    col: at?.col ?? p.col,
    kind: p.kind,
    row_span: p.row_span,
    col_span: p.col_span,
    card_variant_id: p.card_variant_id,
    insert_asset_id: p.insert_asset_id,
    spans_gutter: p.spans_gutter,
    z_order: p.z_order,
  };
}

/** A card in the collection pool, draggable into a pocket. */
function PoolCard({ card }: { card: CardOut }) {
  const canonical = card.variants.find((v) => v.is_canonical) ?? card.variants[0];
  const { attributes, listeners, setNodeRef, isDragging } = useDraggable({
    id: `pool:${canonical?.id ?? 0}`,
    data: { variantId: canonical?.id, card },
    disabled: !canonical,
  });

  return (
    <div
      ref={setNodeRef}
      {...listeners}
      {...attributes}
      role="button"
      aria-label={`${card.number} ${card.name}${card.is_owned ? ", owned" : ", not owned"}`}
      className={`flex cursor-grab touch-none items-center gap-2 rounded-lg border p-1.5 text-left transition-colors active:cursor-grabbing ${
        isDragging ? "opacity-25" : ""
      } ${card.is_owned ? "border-accent-line bg-accent-surface" : "border-line bg-raised"}`}
    >
      {card.image_small ? (
        <img
          src={card.image_small}
          alt=""
          className="aspect-card w-8 flex-none rounded-[3px] bg-well object-cover"
          loading="lazy"
          draggable={false}
        />
      ) : (
        <div className="hatch aspect-card w-8 flex-none rounded-[3px] border border-line-card" />
      )}
      <div className="flex min-w-0 flex-col">
        <span className="font-mono text-[10px] font-medium text-accent-text">{card.number}</span>
        <span className="truncate text-[11.5px] leading-tight text-ink-2">{card.name}</span>
      </div>
    </div>
  );
}

/**
 * Drop on the pocket under the POINTER, not the pocket the dragged rectangle happens to overlap
 * most.
 *
 * dnd-kit defaults to `rectIntersection`, which scores droppables by area of overlap with the
 * dragged element. A card tile dragged out of the collection pool is far wider than a pocket, so
 * its rectangle straddles three of them at once and the leftmost neighbour can win -- the card
 * lands one pocket away from where it was dropped, silently overwriting whatever was there.
 * `pointerWithin` is exact for a grid like this; `closestCenter` is the fallback for the keyboard
 * sensor, which has no pointer to test.
 */
const collisionDetection: CollisionDetection = (args) => {
  const underPointer = pointerWithin(args);
  return underPointer.length > 0 ? underPointer : closestCenter(args);
};

/** The adjustable score terms, in the order docs/05-binder-spec.md lists them. */
const WEIGHT_FIELDS: { key: keyof MichiWeights; label: string; hint: string }[] = [
  { key: "symmetry", label: "symmetry", hint: "Placements mirrored about the spread's centre" },
  { key: "colour", label: "colour", hint: "Adjacent cards close in CIELAB (needs extracted colours)" },
  { key: "hero", label: "hero", hint: "How central the spread's standout card sits" },
  { key: "fill", label: "fill", hint: "Empty pockets spread evenly rather than piled on one page" },
  { key: "orphan", label: "orphan", hint: "Penalty when a group is split across non-adjacent spreads" },
];

/** Fetch a binary export and hand it to the browser as a download.
 *
 * Same blob-and-anchor dance as the goal shopping-list export in GoalDetailPage -- deliberately
 * not a second download mechanism. The difference is that these come back binary, so the response
 * is read as a blob rather than text, and a failed request carries a JSON `detail` worth showing
 * (an export refuses on things the user can fix: no inserts placed, art too big for the sheet).
 */
async function downloadExport(url: string, filename: string): Promise<void> {
  const res = await fetch(url);
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* not JSON; the status is all we have */
    }
    throw new Error(detail);
  }
  const blobUrl = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = blobUrl;
  a.download = filename;
  // Attached before clicking, and the URL revoked on a timer rather than synchronously. This is
  // defensive rather than a fix for anything observed here: a detached anchor is ignored by some
  // browsers, and revoking immediately can in principle pull the blob out from under a download
  // that has not finished reading it. GoalDetailPage's text export does neither and works fine,
  // so if these two ever get factored together, that is the direction to move it.
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(blobUrl), 10_000);
}

export default function BinderDesignerPage() {
  const { binderId: binderIdParam } = useParams();
  const binderId = Number(binderIdParam);

  const { data: layout, isLoading, error } = useBinderLayout(binderId);
  const setPlacements = useSetPlacements(binderId);
  const autoLayout = useAutoLayout(binderId);
  const michiLayout = useMichiLayout(binderId);
  const { data: sets } = useSets();

  const [spreadIndex, setSpreadIndex] = useState(0);
  const [pageSize, setPageSize] = useState<"letter" | "a4">("letter");
  const [clusterKey, setClusterKey] = useState<ClusterKey>("species");
  const [weights, setWeights] = useState<MichiWeights>(DEFAULT_MICHI_WEIGHTS);
  const [exporting, setExporting] = useState<"pdf" | "png" | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [poolSetId, setPoolSetId] = useState<string>("");
  const [ownedOnly, setOwnedOnly] = useState(false);
  const [dragging, setDragging] = useState<
    { kind: "pool"; card: CardOut } | { kind: "placement"; placement: PlacementOut } | null
  >(null);
  const [undoStack, setUndoStack] = useState<Edit[]>([]);
  const [redoStack, setRedoStack] = useState<Edit[]>([]);
  const [mode, setMode] = useState<"set_order" | "rarity_tiered" | "michi">("set_order");

  const { data: poolSet } = useSetDetail(poolSetId || undefined);

  const sensors = useSensors(useSensor(PointerSensor, {
    // A few pixels of slop, so a click on the remove button is not read as a drag.
    activationConstraint: { distance: 4 },
  }), useSensor(KeyboardSensor));

  const byCell = useMemo(() => {
    const m = new Map<string, PlacementOut>();
    for (const p of layout?.placements ?? []) {
      m.set(`${p.page_index}:${p.row}:${p.col}`, p);
    }
    return m;
  }, [layout]);

  const run = useCallback(
    (edit: Edit) => {
      setPlacements.mutate(edit.apply, {
        onSuccess: () => {
          setUndoStack((s) => [...s, edit]);
          setRedoStack([]);
        },
      });
    },
    [setPlacements],
  );

  const undo = useCallback(() => {
    const edit = undoStack[undoStack.length - 1];
    if (!edit || setPlacements.isPending) return;
    setPlacements.mutate(edit.invert, {
      onSuccess: () => {
        setUndoStack((s) => s.slice(0, -1));
        setRedoStack((s) => [...s, edit]);
      },
    });
  }, [undoStack, setPlacements]);

  const redo = useCallback(() => {
    const edit = redoStack[redoStack.length - 1];
    if (!edit || setPlacements.isPending) return;
    setPlacements.mutate(edit.apply, {
      onSuccess: () => {
        setRedoStack((s) => s.slice(0, -1));
        setUndoStack((s) => [...s, edit]);
      },
    });
  }, [redoStack, setPlacements]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "z") return;
      e.preventDefault();
      if (e.shiftKey) redo();
      else undo();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [undo, redo]);

  function handleDragStart(event: DragStartEvent) {
    const data = event.active.data.current;
    if (data?.card) setDragging({ kind: "pool", card: data.card as CardOut });
    else if (data?.placementId) {
      const from = data.from as { pageIndex: number; row: number; col: number };
      const placement = byCell.get(`${from.pageIndex}:${from.row}:${from.col}`);
      if (placement) setDragging({ kind: "placement", placement });
    }
  }

  function handleDragEnd(event: DragEndEvent) {
    setDragging(null);
    const overId = event.over?.id;
    if (typeof overId !== "string" || !overId.startsWith("pocket:")) return;

    const to = parsePocketId(overId);
    const target = byCell.get(`${to.pageIndex}:${to.row}:${to.col}`);
    const data = event.active.data.current;

    // Dropping a card from the collection pool.
    if (data?.variantId) {
      const cell = { page_index: to.pageIndex, row: to.row, col: to.col };
      run({
        apply: { upserts: [{ ...cell, kind: "card", card_variant_id: data.variantId as number }] },
        invert: target
          ? { upserts: [asUpsert(target)] }
          : { clears: [cell] },
      });
      return;
    }

    // Moving a placement already in the binder.
    const from = data?.from as { pageIndex: number; row: number; col: number } | undefined;
    if (!from) return;
    const source = byCell.get(`${from.pageIndex}:${from.row}:${from.col}`);
    if (!source) return;
    const fromCell = { page_index: from.pageIndex, row: from.row, col: from.col };
    const toCell = { page_index: to.pageIndex, row: to.row, col: to.col };
    if (
      fromCell.page_index === toCell.page_index &&
      fromCell.row === toCell.row &&
      fromCell.col === toCell.col
    ) {
      return;
    }

    if (target) {
      // Drop onto an occupied pocket swaps the two, per docs/05-binder-spec.md.
      run({
        apply: { upserts: [asUpsert(source, toCell), asUpsert(target, fromCell)] },
        invert: { upserts: [asUpsert(source, fromCell), asUpsert(target, toCell)] },
      });
    } else {
      run({
        apply: { upserts: [asUpsert(source, toCell)], clears: [fromCell] },
        invert: { upserts: [asUpsert(source, fromCell)], clears: [toCell] },
      });
    }
  }

  function handleRemove(placement: PlacementOut) {
    const cell = {
      page_index: placement.page_index,
      row: placement.row,
      col: placement.col,
    };
    run({ apply: { clears: [cell] }, invert: { upserts: [asUpsert(placement)] } });
  }

  function handleMichiLayout() {
    if (!poolSet) return;
    michiLayout.mutate(
      { set_id: poolSet.id, cluster_key: clusterKey, weights },
      {
        // Same as the other modes: a whole-binder rewrite has no small inverse batch.
        onSuccess: () => {
          setUndoStack([]);
          setRedoStack([]);
        },
      },
    );
  }

  function handleAutoLayout() {
    if (!poolSet) return;
    autoLayout.mutate(
      // Narrowed: handleAutoLayout is only reachable when the mode is not michi, which has
      // its own endpoint.
      { set_id: poolSet.id, mode: mode as "set_order" | "rarity_tiered" },
      {
        // Auto-layout rewrites the whole binder; there is no small inverse batch that would
        // undo it, so the history is dropped rather than left holding stale cells.
        onSuccess: () => {
          setUndoStack([]);
          setRedoStack([]);
        },
      },
    );
  }

  if (isLoading) return <LoadingState label="Loading binder" />;
  if (error) return <ErrorState message={(error as Error).message} />;
  if (!layout) return <ErrorState message="Binder not found" />;

  const spreadCount = Math.ceil(layout.pages / 2);
  const slug = layout.name.replace(/[^a-z0-9]+/gi, "-").toLowerCase() || "binder";
  // Captured out of the closure: TypeScript will not carry the `if (!layout) return` narrowing
  // into a function declaration.
  const exportBinderId = layout.id;

  async function runExport(kind: "pdf" | "png") {
    setExportError(null);
    setExporting(kind);
    try {
      if (kind === "pdf") {
        await downloadExport(
          `/api/v1/binders/${exportBinderId}/export/inserts.pdf?page_size=${pageSize}`,
          `${slug}-inserts-${pageSize}.pdf`,
        );
      } else {
        await downloadExport(
          `/api/v1/binders/${exportBinderId}/export/spread/${spreadIndex}.png`,
          `${slug}-spread-${spreadIndex + 1}.png`,
        );
      }
    } catch (err) {
      setExportError((err as Error).message);
    } finally {
      setExporting(null);
    }
  }

  const poolCards = (poolSet?.cards ?? []).filter((c) => !ownedOnly || c.is_owned);

  return (
    <Page>
      <PageHeader
        title={layout.name}
        subtitle={`${layout.rows}×${layout.cols} · ${layout.pages} pages · ${
          layout.is_side_loading ? "side-loading" : "top-loading"
        }`}
        back={{ to: "/binders", label: "Binders" }}
      >
        {layout.not_owned_count > 0 && (
          <Tag tone="warn">{layout.not_owned_count} NOT OWNED</Tag>
        )}
        <Tag tone="neutral">{layout.placements.length} PLACED</Tag>
        <Button variant="secondary" onClick={undo} disabled={!undoStack.length}>
          Undo
        </Button>
        <Button variant="secondary" onClick={redo} disabled={!redoStack.length}>
          Redo
        </Button>
        <Segmented<"letter" | "a4">
          value={pageSize}
          onChange={setPageSize}
          options={[
            { value: "letter", label: "LETTER" },
            { value: "a4", label: "A4" },
          ]}
        />
        <Button
          variant="secondary"
          onClick={() => runExport("pdf")}
          disabled={exporting !== null}
          title="Print-ready insert sheets at exact size. Print at 100% scale."
        >
          {exporting === "pdf" ? "Exporting..." : "Insert PDF"}
        </Button>
        <Button
          variant="secondary"
          onClick={() => runExport("png")}
          disabled={exporting !== null}
          title="Preview this spread as a PNG"
        >
          {exporting === "png" ? "Rendering..." : "Spread PNG"}
        </Button>
      </PageHeader>

      {exportError && (
        <Callout tone="danger" className="mb-4">
          {exportError}
        </Callout>
      )}

      {setPlacements.isError && (
        <Callout tone="danger" className="mb-4">
          {(setPlacements.error as Error).message}
        </Callout>
      )}

      <DndContext
          sensors={sensors}
          collisionDetection={collisionDetection}
          onDragStart={handleDragStart}
          onDragEnd={handleDragEnd}
        >
        <div className="flex flex-col gap-5 xl:flex-row">
          <Panel className="flex w-full flex-none flex-col gap-3 p-4 lg:w-72">
            <SectionLabel>Collection pool</SectionLabel>

            <Field label="Set">
              <Select value={poolSetId} onChange={(e) => setPoolSetId(e.target.value)}>
                <option value="">Choose a set...</option>
                {sets?.map((s) => (
                  <option key={s.ptcg_set_id} value={s.ptcg_set_id}>
                    {s.name}
                  </option>
                ))}
              </Select>
            </Field>

            <div className="flex items-center gap-2">
              <Chip active={ownedOnly} onClick={() => setOwnedOnly((v) => !v)}>
                owned only
              </Chip>
              <span className="font-mono text-[11px] text-ink-3">{poolCards.length} cards</span>
            </div>

            {poolSetId && (
              <div className="flex flex-col gap-2 border-t border-line pt-3">
                <SectionLabel>Auto-layout</SectionLabel>
                <Segmented
                  value={mode}
                  onChange={(v) => setMode(v)}
                  options={[
                    { value: "set_order", label: "set order" },
                    { value: "rarity_tiered", label: "rarity" },
                    { value: "michi", label: "michi" },
                  ]}
                />

                {mode === "michi" && (
                  <div className="flex flex-col gap-2 rounded-lg border border-line bg-inset p-2.5">
                    <label className="font-mono text-[11px] uppercase tracking-[0.08em] text-ink-3">
                      Group by
                    </label>
                    <Select
                      value={clusterKey}
                      onChange={(e) => setClusterKey(e.target.value as ClusterKey)}
                      aria-label="Michi cluster key"
                    >
                      <option value="species">Pokemon species</option>
                      <option value="artist">Illustrator</option>
                      <option value="colour">Dominant colour</option>
                      <option value="evolution">Evolution line</option>
                    </Select>

                    <div className="flex items-center justify-between">
                      <SectionLabel>Score weights</SectionLabel>
                      <button
                        type="button"
                        className="font-mono text-[10.5px] text-ink-3 underline hover:text-ink"
                        onClick={() => setWeights(DEFAULT_MICHI_WEIGHTS)}
                      >
                        reset
                      </button>
                    </div>
                    {WEIGHT_FIELDS.map(({ key, label, hint }) => (
                      <div key={String(key)} className="flex items-center gap-2">
                        <span
                          className="w-[68px] shrink-0 font-mono text-[10.5px] text-ink-3"
                          title={hint}
                        >
                          {label}
                        </span>
                        <input
                          type="range"
                          min={0}
                          max={1}
                          step={0.05}
                          value={weights[key]}
                          aria-label={`${label} weight`}
                          onChange={(e) =>
                            setWeights((prev: MichiWeights) => ({ ...prev, [key]: Number(e.target.value) }))
                          }
                          className="h-1 flex-1 accent-accent"
                        />
                        <span className="w-8 shrink-0 text-right font-mono text-[10.5px] text-ink-2">
                          {weights[key].toFixed(2)}
                        </span>
                      </div>
                    ))}
                    <p className="text-[10.5px] leading-snug text-ink-3">
                      Weights are taste, not truth — they decide which of the best-of-24 candidate
                      layouts wins. Colour needs <code>bb binder extract-colors</code> to have run.
                    </p>
                  </div>
                )}

                <Button
                  variant="secondary"
                  onClick={mode === "michi" ? handleMichiLayout : handleAutoLayout}
                  disabled={autoLayout.isPending || michiLayout.isPending}
                >
                  {autoLayout.isPending || michiLayout.isPending
                    ? "Laying out..."
                    : "Fill binder"}
                </Button>
                <p className="text-[11px] text-ink-3">
                  Replaces every placement and clears the undo history.
                </p>
                {mode === "michi" && michiLayout.data && (
                  <div className="flex flex-col gap-1 rounded-lg border border-line bg-inset p-2.5">
                    <p className="text-[11.5px] text-ink-2">
                      Placed {michiLayout.data.placed} across {michiLayout.data.groups} spreads
                      {michiLayout.data.unplaced > 0 &&
                        `; ${michiLayout.data.unplaced} left over`}
                      , best of {michiLayout.data.trials}.
                    </p>
                    <p className="font-mono text-[11px] text-ink">
                      score {michiLayout.data.score.total.toFixed(3)}
                    </p>
                    {(["symmetry", "colour", "hero", "fill"] as const).map((term) => {
                      const value = michiLayout.data!.score[term];
                      return (
                        <div key={term} className="flex justify-between font-mono text-[10.5px]">
                          <span className="text-ink-3">{term}</span>
                          <span className={value === null ? "text-ink-4" : "text-ink-2"}>
                            {value === null ? "not measured" : value.toFixed(3)}
                          </span>
                        </div>
                      );
                    })}
                    <div className="flex justify-between font-mono text-[10.5px]">
                      <span className="text-ink-3">orphan</span>
                      <span className="text-ink-2">
                        {michiLayout.data.score.orphan.toFixed(3)} penalty
                      </span>
                    </div>
                    {michiLayout.data.score.unmeasured.includes("colour") && (
                      <p className="text-[10.5px] text-warn-text">
                        Colour did not count: no card in this set has an extracted colour yet.
                      </p>
                    )}
                  </div>
                )}
                {michiLayout.isError && (
                  <Callout tone="danger">{(michiLayout.error as Error).message}</Callout>
                )}

                {autoLayout.data && mode !== "michi" && (
                  <>
                    <p className="text-[11.5px] text-ink-2">
                      Placed {autoLayout.data.placed} across {autoLayout.data.pages_used} pages
                      {autoLayout.data.unplaced > 0 &&
                        `; ${autoLayout.data.unplaced} did not fit`}
                      .
                    </p>
                    {autoLayout.data.skipped_no_variant > 0 && (
                      <Callout tone="warn">
                        {autoLayout.data.skipped_no_variant} cards in this set have no priced
                        variant, so nothing could be placed for them. Ingest this set&rsquo;s
                        prices to pick them up.
                      </Callout>
                    )}
                  </>
                )}
              </div>
            )}

            <div className="flex max-h-[60vh] flex-col gap-1.5 overflow-y-auto">
              {poolCards.map((c) => (
                <PoolCard key={c.id} card={c} />
              ))}
            </div>
          </Panel>

          <Panel className="min-w-0 flex-1 p-4">
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <SectionLabel>
                Spread {spreadIndex + 1} of {spreadCount}
              </SectionLabel>
              <div className="flex-1" />
              <Button
                variant="secondary"
                onClick={() => setSpreadIndex((i) => Math.max(0, i - 1))}
                disabled={spreadIndex === 0}
              >
                &larr; Previous
              </Button>
              <Button
                variant="secondary"
                onClick={() => setSpreadIndex((i) => Math.min(spreadCount - 1, i + 1))}
                disabled={spreadIndex >= spreadCount - 1}
              >
                Next &rarr;
              </Button>
            </div>

            <SpreadView layout={layout} spreadIndex={spreadIndex} onRemove={handleRemove} />
          </Panel>

          <div className="w-full flex-none xl:w-[24rem]">
            <BinderContents
              layout={layout}
              spreadIndex={spreadIndex}
              onJumpToSpread={setSpreadIndex}
              onRemove={handleRemove}
            />
          </div>
        </div>

        <DragOverlay>
          {dragging?.kind === "placement" ? (
            <div className="aspect-pocket w-24 rounded-md border border-accent bg-raised p-[3px] shadow-lift">
              <PlacedCard placement={dragging.placement} />
            </div>
          ) : dragging?.kind === "pool" ? (
            <div className="aspect-pocket w-24 overflow-hidden rounded-md border border-accent bg-raised p-[3px] shadow-lift">
              {dragging.card.image_small ? (
                <img
                  src={dragging.card.image_small}
                  alt=""
                  className="h-full w-full rounded-[5px] object-cover"
                />
              ) : (
                <div className="hatch h-full w-full rounded-[5px]" />
              )}
            </div>
          ) : null}
        </DragOverlay>
      </DndContext>
    </Page>
  );
}
