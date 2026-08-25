import { useState } from "react";
import { Link } from "react-router-dom";
import { useCreateGoal, useGoals, useSets } from "../lib/queries";

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
      { onSuccess: () => setName("") }
    );
  }

  return (
    <div className="mx-auto max-w-3xl p-6">
      <h1 className="mb-4 text-xl font-semibold">Goals</h1>

      <form
        onSubmit={handleSubmit}
        className="mb-8 flex flex-col gap-3 rounded-lg border border-neutral-200 bg-white p-4 sm:flex-row sm:items-end"
      >
        <div className="flex-1">
          <label className="mb-1 block text-xs font-medium text-neutral-600">Name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Surging Sparks master set"
            className="w-full rounded border border-neutral-300 px-2 py-1.5 text-sm"
          />
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-neutral-600">Type</label>
          <select
            value={goalType}
            onChange={(e) => setGoalType(e.target.value as "set" | "master_set")}
            className="rounded border border-neutral-300 px-2 py-1.5 text-sm"
          >
            <option value="set">Set</option>
            <option value="master_set">Master set</option>
          </select>
        </div>
        <div className="flex-1">
          <label className="mb-1 block text-xs font-medium text-neutral-600">Set</label>
          <select
            value={setId}
            onChange={(e) => setSetId(e.target.value ? Number(e.target.value) : "")}
            className="w-full rounded border border-neutral-300 px-2 py-1.5 text-sm"
          >
            <option value="">Choose a set...</option>
            {sets?.map((s) => (
              <option key={s.ptcg_set_id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </div>
        <button
          type="submit"
          disabled={!canSubmit || createGoal.isPending}
          className="rounded bg-neutral-900 px-4 py-1.5 text-sm font-medium text-white disabled:opacity-40"
        >
          {createGoal.isPending ? "Creating..." : "Create goal"}
        </button>
      </form>

      {goalsLoading ? (
        <p className="text-neutral-500">Loading goals...</p>
      ) : !goals || goals.length === 0 ? (
        <p className="text-neutral-500">No goals yet -- create one above.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {goals.map((g) => (
            <Link
              key={g.id}
              to={`/goals/${g.id}`}
              className="flex items-center justify-between rounded-lg border border-neutral-200 bg-white p-3 transition hover:border-neutral-400 hover:shadow-sm"
            >
              <span className="text-sm font-medium text-neutral-800">{g.name}</span>
              <span className="text-xs uppercase tracking-wide text-neutral-500">
                {g.goal_type.replace("_", " ")}
              </span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
