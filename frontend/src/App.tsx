import { Suspense, lazy } from "react";
import { Route, Routes } from "react-router-dom";
import Nav from "./components/Nav";
import { LoadingState } from "./components/ui";
import BinderDesignerPage from "./pages/BinderDesignerPage";
import BindersPage from "./pages/BindersPage";
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
    <div className="min-h-screen bg-canvas text-ink">
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
                    <Suspense fallback={<LoadingState />}>
                      <PortfolioPage />
                    </Suspense>
                  }
                />
                <Route path="/binders" element={<BindersPage />} />
                <Route path="/binders/:binderId" element={<BinderDesignerPage />} />
                <Route path="/goals" element={<GoalsPage />} />
                <Route path="/goals/:goalId" element={<GoalDetailPage />} />
                <Route
                  path="/goals/:goalId/simulate"
                  element={
                    <Suspense fallback={<LoadingState />}>
                      <GoalSimulatePage />
                    </Suspense>
                  }
                />
              </Routes>
            </>
          }
        />
      </Routes>
    </div>
  );
}
