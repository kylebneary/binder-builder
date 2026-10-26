import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useCardFacets, useCreateGoal, useGoals, useSets } from "../lib/queries";
import type { GoalIn } from "../lib/types";
import {
  Button,
  ButtonLink,
  EmptyState,
  Field,
  Input,
  Page,
  PageHeader,
  Panel,
  SectionLabel,
  Segmented,
  Select,
  Tag,
} from "../components/ui";

/**
 * Goal templates. Each one is a shortcut to a goal type the backend already understands:
 *
 * - set / master set  -> SET / MASTER_SET goals
 * - Pokemon / artist / energy type -> live FILTER goals, which pick up newly ingested sets on
 *   resync. They are the same filters the card search uses, so "every Pikachu" here and the
 *   Pokemon filter on /cards agree card for card.
 * - build your own    -> the card search, which saves CUSTOM (hand-picked) or FILTER goals.
 */
type Template = "set" | "master_set" | "pokemon" | "artist" | "type";

const TEMPLATES: { value: Template; label: string; hint: string }[] = [
  { value: "set", label: "Set", hint: "One copy of every card in a set." },
  { value: "master_set", label: "Master set", hint: "Every printing, reverse holos included." },
  { value: "pokemon", label: "A Pokémon", hint: "Every card of one species, across every set." },
  { value: "artist", label: "An illustrator", hint: "Every card one artist drew." },
  { value: "type", label: "An energy type", hint: "Every Fire card, every Psychic card..." },
];

const GOAL_TYPE_LABEL: Record<string, string> = {
  set: "SET",
  master_set: "MASTER SET",
  filter: "LIVE FILTER",
  custom: "CUSTOM",
};

export default function GoalsPage() {
  const { data: goals, isLoading: goalsLoading } = useGoals();
  const { data: sets } = useSets();
  const { data: facets } = useCardFacets();
  const createGoal = useCreateGoal();
  const navigate = useNavigate();

  const [template, setTemplate] = useState<Template>("set");
  const [name, setName] = useState("");
  const [setId, setSetId] = useState<number | "">("");
  const [pick, setPick] = useState("");
  const [allPrintings, setAllPrintings] = useState(false);

  const species = facets?.species ?? [];
  const pokemon = species.find((s) => s.name.toLowerCase() === pick.trim().toLowerCase());
  const artist = facets?.artists.find((a) => a.value.toLowerCase() === pick.trim().toLowerCase());
  const energy = facets?.types.find((t) => t.value === pick);
  const isSetTemplate = template === "set" || template === "master_set";

  // The suggested name, used when the name box is left empty.
  const suggested = isSetTemplate
    ? (() => {
        const s = sets?.find((x) => x.id === setId);
        return s ? `${s.name}${template === "master_set" ? " master set" : ""}` : "";
      })()
    : template === "pokemon" && pokemon
      ? `Every ${pokemon.name} card`
      : template === "artist" && artist
        ? `Every ${artist.value} card`
        : template === "type" && energy
          ? `Every ${energy.value} card`
          : "";

  function body(): GoalIn | null {
    const goalName = name.trim() || suggested;
    if (!goalName) return null;
    if (isSetTemplate) {
      return setId === "" ? null : { name: goalName, goal_type: template, set_id: setId };
    }
    const scope = allPrintings ? ("all" as const) : ("canonical" as const);
    if (template === "pokemon" && pokemon) {
      return {
        name: goalName,
        goal_type: "filter",
        query: { pokedex_numbers: [pokemon.pokedex_number], variant_scope: scope },
      };
    }
    if (template === "artist" && artist) {
      return {
        name: goalName,
        goal_type: "filter",
        query: { artists: [artist.value], variant_scope: scope },
      };
    }
    if (template === "type" && energy) {
      return {
        name: goalName,
        goal_type: "filter",
        query: { types: [energy.value], variant_scope: scope },
      };
    }
    return null;
  }

  const ready = body();

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!ready) return;
    createGoal.mutate(ready, {
      onSuccess: (goal) => navigate(`/goals/${goal.id}`),
    });
  }

  /** The same filter, opened in the card search to look before committing. */
  function previewHref(): string | null {
    if (template === "pokemon" && pokemon) return `/cards?dex=${pokemon.pokedex_number}`;
    if (template === "artist" && artist) return `/cards?artist=${encodeURIComponent(artist.value)}`;
    if (template === "type" && energy) return `/cards?type=${encodeURIComponent(energy.value)}`;
    return null;
  }
  const preview = previewHref();

  return (
    <Page width="narrow">
      <PageHeader title="Goals" subtitle="What you are trying to complete, and what it costs">
        <ButtonLink to="/cards" variant="secondary">
          Build a custom goal
        </ButtonLink>
      </PageHeader>

      <Panel className="mb-6 flex flex-col gap-4 p-4">
        <SectionLabel>New goal from a template</SectionLabel>
        <div className="flex flex-wrap gap-2">
          {TEMPLATES.map((t) => (
            <button
              key={t.value}
              type="button"
              aria-pressed={template === t.value}
              onClick={() => {
                setTemplate(t.value);
                setPick("");
              }}
              className={`flex w-[9.5rem] flex-col gap-0.5 rounded-lg border px-3 py-2 text-left transition-colors ${
                template === t.value
                  ? "border-accent bg-accent-surface"
                  : "border-line bg-raised hover:border-accent-line"
              }`}
            >
              <span className="text-[12.5px] font-semibold text-ink">{t.label}</span>
              <span className="text-[10.5px] leading-snug text-ink-3">{t.hint}</span>
            </button>
          ))}
          <Link
            to="/cards"
            className="flex w-[9.5rem] flex-col gap-0.5 rounded-lg border border-dashed border-line-strong px-3 py-2 text-left transition-colors hover:border-accent-line"
          >
            <span className="text-[12.5px] font-semibold text-ink">Build your own</span>
            <span className="text-[10.5px] leading-snug text-ink-3">
              Search by anything and hand-pick cards.
            </span>
          </Link>
        </div>

        <form onSubmit={handleSubmit} className="flex flex-col gap-3.5">
          <div className="flex flex-col gap-3.5 sm:flex-row sm:items-end">
            <div className="flex-1">
              {isSetTemplate ? (
                <Field label="Set">
                  <Select
                    value={setId}
                    onChange={(e) => setSetId(e.target.value ? Number(e.target.value) : "")}
                  >
                    <option value="">Choose a set...</option>
                    {sets?.map((s) => (
                      <option key={s.ptcg_set_id} value={s.id}>
                        {s.name}
                      </option>
                    ))}
                  </Select>
                </Field>
              ) : template === "type" ? (
                <Field label="Energy type">
                  <Select value={pick} onChange={(e) => setPick(e.target.value)}>
                    <option value="">Choose a type...</option>
                    {facets?.types.map((t) => (
                      <option key={t.value} value={t.value}>
                        {t.value} ({t.count})
                      </option>
                    ))}
                  </Select>
                </Field>
              ) : (
                <Field
                  label={template === "pokemon" ? "Pokémon" : "Illustrator"}
                  hint={
                    pick && !(template === "pokemon" ? pokemon : artist)
                      ? "Pick a name from the list."
                      : template === "pokemon" && pokemon
                        ? `${pokemon.count} cards in the catalogue, including ex/V forms and tag teams. Unpriced ones join the goal once priced.`
                        : template === "artist" && artist
                          ? `${artist.count} cards in the catalogue. Unpriced ones join the goal once priced.`
                          : undefined
                  }
                >
                  <Input
                    list={`goal-${template}`}
                    value={pick}
                    onChange={(e) => setPick(e.target.value)}
                    placeholder={template === "pokemon" ? "Pikachu" : "Mitsuhiro Arita"}
                  />
                  <datalist id={`goal-${template}`}>
                    {template === "pokemon"
                      ? species.map((s) => <option key={s.pokedex_number} value={s.name} />)
                      : facets?.artists.map((a) => <option key={a.value} value={a.value} />)}
                  </datalist>
                </Field>
              )}
            </div>
            <div className="flex-1">
              <Field label="Name">
                <Input
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder={suggested || "Goal name"}
                />
              </Field>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-3">
            {!isSetTemplate && (
              <Segmented
                value={allPrintings ? "all" : "one"}
                onChange={(v) => setAllPrintings(v === "all")}
                options={[
                  { value: "one", label: "one per card" },
                  { value: "all", label: "every printing" },
                ]}
              />
            )}
            <div className="flex-1" />
            {preview && (
              <Link to={preview} className="text-[12.5px] font-medium text-ink-3 hover:text-ink">
                Preview in card search &rarr;
              </Link>
            )}
            <Button type="submit" disabled={!ready || createGoal.isPending}>
              {createGoal.isPending ? "Creating..." : "Create goal"}
            </Button>
          </div>
          {!isSetTemplate && (
            <p className="text-[11px] text-ink-3">
              Live goals re-run their filter when resynced, so cards from newly ingested sets are
              added automatically.
            </p>
          )}
        </form>
        {createGoal.isError && (
          <p className="text-[12px] text-danger-text">{(createGoal.error as Error).message}</p>
        )}
      </Panel>

      {goalsLoading ? (
        <p className="font-mono text-[12px] uppercase tracking-[0.08em] text-ink-3">
          Loading goals
        </p>
      ) : !goals || goals.length === 0 ? (
        <EmptyState title="No goals yet">
          Start from a template above, or build your own list from the card search.
        </EmptyState>
      ) : (
        <div className="flex flex-col gap-2">
          {goals.map((g) => (
            <Link
              key={g.id}
              to={`/goals/${g.id}`}
              className="flex items-center justify-between gap-4 rounded-[11px] border border-line bg-raised px-4 py-3.5 shadow-panel transition-colors hover:border-accent-line"
            >
              <div className="flex min-w-0 flex-col gap-0.5">
                <span className="truncate text-[13.5px] font-semibold text-ink">{g.name}</span>
                <span className="text-[11.5px] text-ink-3">
                  Target condition {g.target_condition}
                </span>
              </div>
              <Tag tone="accent">{GOAL_TYPE_LABEL[g.goal_type] ?? g.goal_type.toUpperCase()}</Tag>
            </Link>
          ))}
        </div>
      )}
    </Page>
  );
}
