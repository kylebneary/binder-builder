import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type {
  CollectionItemIn,
  CollectionItemOut,
  GoalDetailOut,
  GoalIn,
  GoalOut,
  PortfolioSummaryOut,
  PortfolioValuePointOut,
  SetDetailOut,
  SetOut,
} from "./types";

export function useSets() {
  return useQuery({
    queryKey: ["sets"],
    queryFn: () => api<SetOut[]>("/sets"),
  });
}

export function useSetDetail(ptcgSetId: string | undefined) {
  return useQuery({
    queryKey: ["sets", ptcgSetId],
    queryFn: () => api<SetDetailOut>(`/sets/${ptcgSetId}`),
    enabled: !!ptcgSetId,
  });
}

export function usePortfolio() {
  return useQuery({
    queryKey: ["portfolio"],
    queryFn: () => api<PortfolioSummaryOut>("/collection/portfolio"),
  });
}

export function usePortfolioHistory() {
  return useQuery({
    queryKey: ["portfolio", "history"],
    queryFn: () => api<PortfolioValuePointOut[]>("/collection/portfolio/history"),
  });
}

/** Upserts a collection_item and invalidates the set detail + portfolio queries that just
 * went stale, so owned/needed flags and portfolio value reflect the change immediately. */
export function useUpsertCollectionItem(ptcgSetId: string | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: CollectionItemIn) =>
      api<CollectionItemOut>("/collection/items", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      if (ptcgSetId) void queryClient.invalidateQueries({ queryKey: ["sets", ptcgSetId] });
      void queryClient.invalidateQueries({ queryKey: ["portfolio"] });
    },
    // "portfolio" key covers both the summary and ["portfolio", "history"] (query keys match by
    // prefix), so no separate invalidation is needed for the history chart.
  });
}

export function useGoals() {
  return useQuery({
    queryKey: ["goals"],
    queryFn: () => api<GoalOut[]>("/goals"),
  });
}

export function useGoalDetail(goalId: number | undefined) {
  return useQuery({
    queryKey: ["goals", goalId],
    queryFn: () => api<GoalDetailOut>(`/goals/${goalId}`),
    enabled: goalId !== undefined,
  });
}

export function useCreateGoal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: GoalIn) =>
      api<GoalOut>("/goals", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["goals"] });
    },
  });
}

export function useDeleteGoal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (goalId: number) => api<void>(`/goals/${goalId}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["goals"] });
    },
  });
}
