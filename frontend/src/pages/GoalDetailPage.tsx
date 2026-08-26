import { useNavigate, useParams } from "react-router-dom";
import { useDeleteGoal, useGoalDetail } from "../lib/queries";
import { formatMoney } from "../lib/types";
import {
  Button,
  ButtonLink,
  Callout,
  ErrorState,
  LoadingState,
  Page,
  PageHeader,
  Stat,
  Table,
  Td,
  Th,
  Tr,
} from "../components/ui";

export default function GoalDetailPage() {
  const { goalId } = useParams<{ goalId: string }>();
  const navigate = useNavigate();
  const id = goalId ? Number(goalId) : undefined;
  const { data: goal, isLoading } = useGoalDetail(id);
  const deleteGoal = useDeleteGoal();

  if (isLoading) return <LoadingState />;
  if (!goal) return <ErrorState message="Goal not found." />;

  const needed = goal.items.filter((i) => i.need_qty > 0);

  return (
    <Page width="narrow">
      <PageHeader
        title={goal.name}
        subtitle={`${goal.goal_type.replace("_", " ")} · target condition ${goal.target_condition}`}
        back={{ to: "/goals", label: "Goals" }}
      >
        <ButtonLink to={`/goals/${goal.id}/simulate`}>Run optimizer</ButtonLink>
        <Button
          variant="danger"
          onClick={() => deleteGoal.mutate(goal.id, { onSuccess: () => navigate("/goals") })}
          disabled={deleteGoal.isPending}
        >
          Delete
        </Button>
      </PageHeader>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Cards needed" value={String(goal.cost.n_cards)} />
        <Stat label="Subtotal" value={formatMoney(goal.cost.subtotal)} />
        <Stat
          label="Shipping"
          value={formatMoney(goal.cost.shipping)}
          hint={`${goal.cost.orders} orders`}
        />
        <Stat label="Singles total" value={formatMoney(goal.cost.total)} tone="positive" />
      </div>

      {goal.unpriced_count > 0 && (
        <Callout className="mt-3.5">
          {goal.unpriced_count} needed card{goal.unpriced_count === 1 ? "" : "s"} have no current
          price and are excluded from the total above.
        </Callout>
      )}

      <h2 className="mb-3 mt-8 text-[14px] font-semibold text-ink">Still needed</h2>
      <Table
        head={
          <>
            <Th className="w-16">#</Th>
            <Th>Card</Th>
            <Th>Variant</Th>
            <Th>Rarity</Th>
            <Th className="text-right">Price</Th>
            <Th className="text-right">Need</Th>
          </>
        }
      >
        {needed.length === 0 ? (
          <Tr>
            <Td colSpan={6} className="py-10 text-center text-[12.5px] text-ink-3">
              Everything in this goal is already owned.
            </Td>
          </Tr>
        ) : (
          needed.map((item) => (
            <Tr key={item.card_variant_id}>
              <Td className="font-mono text-[11.5px] text-accent-text">{item.number}</Td>
              <Td className="font-medium text-ink">{item.card_name}</Td>
              <Td className="text-ink-3">{item.variant}</Td>
              <Td className="text-ink-3">{item.rarity ?? "—"}</Td>
              <Td className="text-right font-mono text-[12px]">
                {formatMoney(item.market_price)}
              </Td>
              <Td className="text-right font-mono text-[12px] font-medium text-ink">
                {item.need_qty}
              </Td>
            </Tr>
          ))
        )}
      </Table>
    </Page>
  );
}
