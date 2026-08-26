import { useState } from "react";
import { Link } from "react-router-dom";
import { useCreateGoal, useGoals, useSets } from "../lib/queries";
import {
  Button,
  EmptyState,
  Field,
  Input,
  Page,
  PageHeader,
  Panel,
  SectionLabel,
  Select,
  Tag,
} from "../components/ui";

// FILTER-type goals are supported by the API but not by this form -- a filter-builder UI is
// deferred until there's a real need for it (docs/06-roadmap.md phase 2 scope).
export default function GoalsPage() {
  const { data: goals, isLoading: goalsLoading } = useGoals();
  const { data: sets } = useSets();
  const createGoal = useCreateGoal();

  const [name, setName] = useState("");
  const [goalType, setGoalType] = useState<"set" | "master_set">("set");
  const [setId, setSetId] = useState<number | "">("");

  const canSubmit = name.trim().length > 0 && setId !== "";

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!canSubmit) return;
    createGoal.mutate(
      { name: name.trim(), goal_type: goalType, set_id: setId as number },
      { onSuccess: () => setName("") },
    );
  }

  return (
    <Page width="narrow">
      <PageHeader title="Goals" subtitle="What you are trying to complete, and what it costs" />

      <Panel className="mb-6 p-4">
        <SectionLabel className="mb-3.5">New goal</SectionLabel>
        <form onSubmit={handleSubmit} className="flex flex-col gap-3.5 sm:flex-row sm:items-end">
          <div className="flex-1">
            <Field label="Name">
              <Input
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="Surging Sparks master set"
              />
            </Field>
          </div>
          <div className="sm:w-40">
            <Field label="Type">
              <Select
                value={goalType}
                onChange={(e) => setGoalType(e.target.value as "set" | "master_set")}
              >
                <option value="set">Set</option>
                <option value="master_set">Master set</option>
              </Select>
            </Field>
          </div>
          <div className="flex-1">
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
          </div>
          <Button type="submit" disabled={!canSubmit || createGoal.isPending}>
            {createGoal.isPending ? "Creating..." : "Create goal"}
          </Button>
        </form>
        {createGoal.isError && (
          <p className="mt-3 text-[12px] text-danger-text">
            {(createGoal.error as Error).message}
          </p>
        )}
      </Panel>

      {goalsLoading ? (
        <p className="font-mono text-[12px] uppercase tracking-[0.08em] text-ink-3">
          Loading goals
        </p>
      ) : !goals || goals.length === 0 ? (
        <EmptyState title="No goals yet">
          Create one above to see the cheapest path to completing it.
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
              <Tag tone="accent">{g.goal_type.replace("_", " ").toUpperCase()}</Tag>
            </Link>
          ))}
        </div>
      )}
    </Page>
  );
}
