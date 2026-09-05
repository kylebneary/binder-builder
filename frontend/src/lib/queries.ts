import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type {
  AutoLayoutIn,
  AutoLayoutOut,
  BinderIn,
  BinderLayoutOut,
  BinderOut,
  CollectionItemIn,
  CollectionItemOut,
  GoalDetailOut,
  GoalIn,
  GoalOut,
  HoldingOut,
  PlacementBatchIn,
  PlacementOut,
  PortfolioSummaryOut,
  PortfolioValuePointOut,
  SealedProductOut,
  SensitivityIn,
  SensitivityOut,
  SetDetailOut,
  SetOut,
  SimulateIn,
  SimulateResponseOut,
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

export function useSealedProducts(ptcgSetId: string | undefined) {
  return useQuery({
    queryKey: ["sets", ptcgSetId, "sealed-products"],
    queryFn: () => api<SealedProductOut[]>(`/sets/${ptcgSetId}/sealed-products`),
    enabled: !!ptcgSetId,
  });
}

/** A real compute call, not a cached read -- a mutation even though it doesn't change server
 * state, so each "Run optimizer" click is explicit and re-triggerable rather than memoized. */
export function useRunSimulation(goalId: number | undefined) {
  return useMutation({
    mutationFn: (body: SimulateIn) =>
      api<SimulateResponseOut>(`/goals/${goalId}/simulate`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
  });
}

export function useRunSensitivity(goalId: number | undefined) {
  return useMutation({
    mutationFn: (body: SensitivityIn) =>
      api<SensitivityOut>(`/goals/${goalId}/sensitivity`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
  });
}

/* ------------------------------------------------------------------- binder */

export function useBinders() {
  return useQuery({
    queryKey: ["binders"],
    queryFn: () => api<BinderOut[]>("/binders"),
  });
}

export function useBinderLayout(binderId: number | undefined) {
  return useQuery({
    queryKey: ["binders", binderId, "layout"],
    queryFn: () => api<BinderLayoutOut>(`/binders/${binderId}/layout`),
    enabled: binderId !== undefined && !Number.isNaN(binderId),
  });
}

export function useCreateBinder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: BinderIn) =>
      api<BinderOut>("/binders", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["binders"] });
    },
  });
}

export function useDeleteBinder() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (binderId: number) => api<void>(`/binders/${binderId}`, { method: "DELETE" }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["binders"] });
    },
  });
}

/** One gesture, one request. The undo stack in BinderDesignerPage holds inverse batches and
 * replays them through this same mutation, so undo needs no special server support. */
export function useSetPlacements(binderId: number | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: PlacementBatchIn) =>
      api<PlacementOut[]>(`/binders/${binderId}/placements`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["binders", binderId, "layout"] });
    },
  });
}

export function useAutoLayout(binderId: number | undefined) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: AutoLayoutIn) =>
      api<AutoLayoutOut>(`/binders/${binderId}/auto-layout`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["binders", binderId, "layout"] });
    },
  });
}

/** The whole collection in one request. Sorting and filtering happen client-side -- see
 * services/portfolio.list_holdings for why the payload is returned whole. */
export function useHoldings() {
  return useQuery({
    queryKey: ["collection", "holdings"],
    queryFn: () => api<HoldingOut[]>("/collection/holdings"),
  });
}
