import { Navigate, Outlet, Route, Routes, useLocation } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { getSession } from "@/lib/auth";
import LoginPage from "@/pages/LoginPage";
import TrackPage from "@/pages/TrackPage";
import FloorBoardPage from "@/pages/FloorBoardPage";
import InventoryPage from "@/pages/InventoryPage";
import GateEntryPage from "@/pages/GateEntryPage";
import WorkforcePage from "@/pages/WorkforcePage";
import QualityPage from "@/pages/QualityPage";
import TracePage from "@/pages/TracePage";
import RecallPage from "@/pages/RecallPage";
import OrdersPage from "@/pages/OrdersPage";
import MonthEndPage from "@/pages/MonthEndPage";
import RecordsPage from "@/pages/RecordsPage";
import UsersPage from "@/pages/UsersPage";
import RolesPage from "@/pages/RolesPage";
import ValidationLogPage from "@/pages/ValidationLogPage";
import RollPassportPage from "@/pages/RollPassportPage";
import QrLabelsPage from "@/pages/QrLabelsPage";
import AlertsPage from "@/pages/AlertsPage";

function RequireAuth() {
  const location = useLocation();
  if (!getSession()) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  return <Outlet />;
}

export default function App() {
  return (
    <Routes>
      {/* public */}
      <Route path="/login" element={<LoginPage />} />
      <Route path="/track/:token" element={<TrackPage />} />

      {/* staff (logged in) */}
      <Route element={<RequireAuth />}>
        {/* Scanned from a QR label on a phone: full-screen, no sidebar (login first, then straight back here) */}
        <Route path="/roll/:code" element={<RollPassportPage />} />
        {/* The owner's phone on the table: full-screen, live alerts over /ws/alerts */}
        <Route path="/alerts" element={<AlertsPage />} />
        <Route element={<AppShell />}>
          <Route index element={<Navigate to="/floor" replace />} />
          <Route path="/floor" element={<FloorBoardPage />} />
          <Route path="/inventory" element={<InventoryPage />} />
          <Route path="/gate" element={<GateEntryPage />} />
          <Route path="/workforce" element={<WorkforcePage />} />
          <Route path="/quality" element={<QualityPage />} />
          <Route path="/trace" element={<TracePage />} />
          <Route path="/recall/:lotCode" element={<RecallPage />} />
          <Route path="/orders" element={<OrdersPage />} />
          <Route path="/month-end" element={<MonthEndPage />} />
          <Route path="/records" element={<RecordsPage />} />
          <Route path="/admin/users" element={<UsersPage />} />
          <Route path="/admin/roles" element={<RolesPage />} />
          <Route path="/admin/validation-log" element={<ValidationLogPage />} />
          <Route path="/labels" element={<QrLabelsPage />} />
        </Route>
      </Route>

      <Route path="*" element={<Navigate to="/floor" replace />} />
    </Routes>
  );
}
