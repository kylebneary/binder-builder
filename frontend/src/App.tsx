import { Suspense, lazy } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import DemoNav from "./components/DemoNav";
import Nav from "./components/Nav";
import { LoadingState } from "./components/ui";
import { DEMO_BINDER_ID } from "./lib/demoData";
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

const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === "true";

/**
 * Standalone binder-designer demo: the only route demoApi.ts backs is the designer itself, so
 * every other path (including "/") redirects straight into the one seeded binder rather than
 * exposing pages -- Sets, Portfolio, Goals -- that would render against nothing.
 */
function DemoApp() {
  return (
    <div className="min-h-screen bg-canvas text-ink">
      <DemoNav />
      <Routes>
        <Route path="/binders/:binderId" element={<BinderDesignerPage />} />
        <Route path="*" element={<Navigate to={`/binders/${DEMO_BINDER_ID}`} replace />} />
      </Routes>
    </div>
  );
}

export default function App() {
  if (DEMO_MODE) return <DemoApp />;

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
