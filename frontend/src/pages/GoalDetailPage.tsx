import { useNavigate, useParams } from "react-router-dom";
import { useDeleteGoal, useGoalDetail } from "../lib/queries";
import { formatMoney } from "../lib/types";

export default function GoalDetailPage() {
  const { goalId } = useParams<{ goalId: string }>();
  const navigate = useNavigate();
  const id = goalId ? Number(goalId) : undefined;
  const { data: goal, isLoading } = useGoalDetail(id);
  const deleteGoal = useDeleteGoal();

  if (isLoading) return <p className="p-6 text-neutral-500">Loading...</p>;
  if (!goal) return <p className="p-6 text-neutral-500">Goal not found.</p>;

  const needed = goal.items.filter((i) => i.need_qty > 0);

  return (
    <div className="mx-auto max-w-4xl p-6">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">{goal.name}</h1>
          <p className="text-xs uppercase tracking-wide text-neutral-500">
            {goal.goal_type.replace("_", " ")}
          </p>
        </div>
        <button
          onClick={() => deleteGoal.mutate(goal.id, { onSuccess: () => navigate("/goals") })}
          className="rounded border border-red-300 px-3 py-1.5 text-sm text-red-600 hover:bg-red-50"
        >
          Delete goal
        </button>
      </div>

      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <StatCard label="Cards needed" value={String(goal.cost.n_cards)} />
        <StatCard label="Subtotal" value={formatMoney(goal.cost.subtotal)} />
        <StatCard
          label="Shipping"
          value={`${formatMoney(goal.cost.shipping)} (${goal.cost.orders} orders)`}
        />
        <StatCard label="Total" value={formatMoney(goal.cost.total)} />
      </div>

      {goal.unpriced_count > 0 && (
        <p className="mt-3 text-xs text-amber-600">
          {goal.unpriced_count} needed card(s) have no current price and are excluded from the
          total above.
        </p>
      )}

      <div className="mt-8 overflow-hidden rounded-lg border border-neutral-200 bg-white">
        <table className="w-full text-sm">
          <thead className="border-b border-neutral-200 bg-neutral-50 text-left text-xs uppercase text-neutral-500">
            <tr>
              <th className="px-3 py-2">#</th>
              <th className="px-3 py-2">Card</th>
              <th className="px-3 py-2">Variant</th>
              <th className="px-3 py-2">Rarity</th>
              <th className="px-3 py-2 text-right">Price</th>
              <th className="px-3 py-2 text-right">Needed</th>
            </tr>
          </thead>
          <tbody>
            {needed.length === 0 ? (
              <tr>
                <td colSpan={6} className="px-3 py-6 text-center text-neutral-400">
                  Everything in this goal is already owned.
                </td>
              </tr>
            ) : (
              needed.map((item) => (
                <tr key={item.card_variant_id} className="border-b border-neutral-100 last:border-0">
                  <td className="px-3 py-2 text-neutral-500">{item.number}</td>
                  <td className="px-3 py-2 font-medium text-neutral-800">{item.card_name}</td>
                  <td className="px-3 py-2 text-neutral-600">{item.variant}</td>
                  <td className="px-3 py-2 text-neutral-600">{item.rarity ?? "—"}</td>
                  <td className="px-3 py-2 text-right text-neutral-600">
                    {formatMoney(item.market_price)}
                  </td>
                  <td className="px-3 py-2 text-right font-medium text-neutral-800">
                    {item.need_qty}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-neutral-200 bg-white p-4">
      <div className="text-xs text-neutral-500">{label}</div>
      <div className="mt-1 text-lg font-semibold text-neutral-900">{value}</div>
    </div>
  );
}
