import { createBrowserRouter, RouterProvider, Navigate } from "react-router-dom";
import { useAuthStore } from "./stores/authStore";
import AdminLayout from "./components/AdminLayout";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import DashboardPage from "./pages/DashboardPage";
import ChatPage from "./pages/ChatPage";
import SearchPage from "./pages/SearchPage";
import CandidatesPage from "./pages/CandidatesPage";
import CandidateDetailPage from "./pages/CandidateDetailPage";
import JobsPage from "./pages/JobsPage";
import JobDetailPage from "./pages/JobDetailPage";
import DocumentsPage from "./pages/DocumentsPage";
import ResumesPage from "./pages/ResumesPage";
import ModelConfigsPage from "./pages/ModelConfigsPage";
import WorkspacePage from "./pages/WorkspacePage";
import InterviewPage from "./pages/InterviewPage";

function RequireAuth({ children }: { children: React.ReactNode }) {
  const authed = useAuthStore((s) => s.isAuthenticated);
  return authed ? <>{children}</> : <Navigate to="/login" />;
}

function ProtectedLayout() {
  return (
    <RequireAuth>
      <AdminLayout />
    </RequireAuth>
  );
}

const router = createBrowserRouter([
  { path: "/login", element: <LoginPage /> },
  { path: "/register", element: <RegisterPage /> },
  {
    element: <ProtectedLayout />,
    children: [
      { path: "/", element: <DashboardPage /> },
      { path: "/chat/:kbId?", element: <ChatPage /> },
      { path: "/search", element: <SearchPage /> },
      { path: "/candidates", element: <CandidatesPage /> },
      { path: "/candidates/:id", element: <CandidateDetailPage /> },
      { path: "/jobs", element: <JobsPage /> },
      { path: "/jobs/:id", element: <JobDetailPage /> },
      { path: "/documents/:kbId?", element: <DocumentsPage /> },
      { path: "/resumes", element: <ResumesPage /> },
      { path: "/models", element: <ModelConfigsPage /> },
      { path: "/workspace", element: <WorkspacePage /> },
      { path: "/interviews", element: <InterviewPage /> },
    ],
  },
]);

export default function App() {
  return <RouterProvider router={router} />;
}