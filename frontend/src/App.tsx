import { Suspense, lazy } from "react";
import { Route, Routes } from "react-router-dom";
import Nav from "./components/Nav";
import BulkEntryPage from "./pages/BulkEntryPage";
import GoalDetailPage from "./pages/GoalDetailPage";
import GoalsPage from "./pages/GoalsPage";
import SetDetailPage from "./pages/SetDetailPage";
import SetListPage from "./pages/SetListPage";

// recharts pulls in a large chunk (~400kB) that only the portfolio dashboard and the optimizer
// results view need -- split both out so the primary set-browsing/bulk-entry path doesn't pay
// for it.
const PortfolioPage = lazy(() => import("./pages/PortfolioPage"));
const GoalSimulatePage = lazy(() => import("./pages/GoalSimulatePage"));

export default function App() {
  return (
    <div className="min-h-screen bg-neutral-50">
      <Routes>
        {/* Bulk entry is a focused, full-screen mode -- no chrome around it. */}
        <Route path="/sets/:ptcgSetId/entry" element={<BulkEntryPage />} />
        <Route
          path="*"
          element={
            <>
              <Nav />
              <Routes>
                <Route path="/" element={<SetListPage />} />
                <Route path="/sets/:ptcgSetId" element={<SetDetailPage />} />
                <Route
                  path="/portfolio"
                  element={
                    <Suspense fallback={<p className="p-6 text-neutral-500">Loading...</p>}>
                      <PortfolioPage />
                    </Suspense>
                  }
                />
                <Route path="/goals" element={<GoalsPage />} />
                <Route path="/goals/:goalId" element={<GoalDetailPage />} />
                <Route
                  path="/goals/:goalId/simulate"
                  element={
                    <Suspense fallback={<p className="p-6 text-neutral-500">Loading...</p>}>
                      <GoalSimulatePage />
                    </Suspense>
                  }
                />
              </Routes>
            </>
          }
        />
      </Routes>
      {/* TODO(phase-3.3): binder designer canvas */}
    </div>
  );
}
