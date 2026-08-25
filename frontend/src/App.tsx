import { Route, Routes } from "react-router-dom";
import Nav from "./components/Nav";
import BulkEntryPage from "./pages/BulkEntryPage";
import SetDetailPage from "./pages/SetDetailPage";
import SetListPage from "./pages/SetListPage";

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
              </Routes>
            </>
          }
        />
      </Routes>
      {/* TODO(phase-2.13): optimizer results view */}
      {/* TODO(phase-3.3): binder designer canvas */}
    </div>
  );
}
