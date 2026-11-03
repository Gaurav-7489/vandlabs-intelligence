import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { lazy } from "react";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router-dom";
import { ToastProvider } from "./components/ui";
import Shell from "./layouts/Shell";
import { ApiError } from "./lib/api";
import { SessionProvider, useSession } from "./lib/session";
import Login from "./routes/Login";

// Route-level code splitting: each area is its own chunk, loaded on first visit.
const Overview = lazy(() => import("./routes/Overview"));
const Knowledge = lazy(() => import("./routes/Knowledge"));
const Insights = lazy(() => import("./routes/Insights"));
const Tasks = lazy(() => import("./routes/Tasks"));
const Ask = lazy(() => import("./routes/Ask"));
const Integrations = lazy(() => import("./routes/Integrations"));
const Admin = lazy(() => import("./routes/Admin"));
const DecisionList = lazy(() => import("./routes/Decisions").then((m) => ({ default: m.DecisionList })));
const DecisionDetail = lazy(() => import("./routes/Decisions").then((m) => ({ default: m.DecisionDetail })));

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 15_000, refetchOnWindowFocus: false, retry: (n, e) => !(e instanceof ApiError && e.status < 500 && e.status !== 429) && n < 2 } },
});

const router = createBrowserRouter([{
  path: "/", element: <Shell />,
  children: [
    { index: true, element: <Overview /> }, { path: "ask", element: <Ask /> }, { path: "knowledge", element: <Knowledge /> },
    { path: "insights", element: <Insights /> }, { path: "decisions", element: <DecisionList /> }, { path: "decisions/:id", element: <DecisionDetail /> },
    { path: "tasks", element: <Tasks /> }, { path: "integrations", element: <Integrations /> }, { path: "admin", element: <Admin /> },
    { path: "*", element: <Navigate to="/" replace /> },
  ],
}]);

function Gate() {
  const { me, status, mfaRequired, signOut } = useSession();
  if (status === "loading") return <main className="grid min-h-screen place-items-center" role="status" aria-label="Restoring session"><div className="skeleton h-10 w-48" /></main>;
  if (status === "anon" || !me) return <Login />;
  if (mfaRequired) {
    return (
      <main className="grid min-h-screen place-items-center p-6"><div className="card max-w-sm space-y-4 p-6 text-center">
        <p className="font-display text-2xl">Multi-factor authentication required</p>
        <p className="text-sm text-ink2">Your role requires a session verified with MFA. Sign in again and complete the MFA challenge.</p>
        <a className="btn btn-primary w-full" href="/api/v1/auth/login?reauth=true">Verify with MFA</a>
        <button className="btn w-full" onClick={() => void signOut()}>Sign out</button></div></main>);
  }
  if (me.memberships.length === 0) {
    return <main className="grid min-h-screen place-items-center p-6 text-center"><p className="max-w-sm">Your account is not a member of any organization yet. Ask an organization owner to add {me.user.email}.</p></main>;
  }
  return <RouterProvider router={router} />;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}><SessionProvider><ToastProvider><Gate /></ToastProvider></SessionProvider></QueryClientProvider>
  );
}
