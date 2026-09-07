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

export default function BinderDesignerPage() {
  const { binderId: binderIdParam } = useParams();
  const binderId = Number(binderIdParam);

  const { data: layout, isLoading, error } = useBinderLayout(binderId);
  const setPlacements = useSetPlacements(binderId);
  const autoLayout = useAutoLayout(binderId);
  const { data: sets } = useSets();

  const [spreadIndex, setSpreadIndex] = useState(0);
  const [poolSetId, setPoolSetId] = useState<string>("");
  const [ownedOnly, setOwnedOnly] = useState(false);
  const [dragging, setDragging] = useState<
    { kind: "pool"; card: CardOut } | { kind: "placement"; placement: PlacementOut } | null
  >(null);
  const [undoStack, setUndoStack] = useState<Edit[]>([]);
  const [redoStack, setRedoStack] = useState<Edit[]>([]);
  const [mode, setMode] = useState<"set_order" | "rarity_tiered">("set_order");

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

  function handleAutoLayout() {
    if (!poolSet) return;
    autoLayout.mutate(
      { set_id: poolSet.id, mode },
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
      </PageHeader>

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
                  ]}
                />
                <Button
                  variant="secondary"
                  onClick={handleAutoLayout}
                  disabled={autoLayout.isPending}
                >
                  {autoLayout.isPending ? "Laying out..." : "Fill binder"}
                </Button>
                <p className="text-[11px] text-ink-3">
                  Replaces every placement and clears the undo history.
                </p>
                {autoLayout.data && (
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
