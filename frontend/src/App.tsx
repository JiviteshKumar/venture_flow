import { Suspense, type ReactNode } from "react";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/layout/Layout";
import { lazyPage } from "./lazyPage";
import { AppProvider } from "./context/AppContext";
import { AuthProvider } from "./context/AuthContext";
import DemoGate from "./components/common/DemoGate";
import RequireAuth from "./components/common/RequireAuth";

/**
 * Provider order is load-bearing.
 *
 * AuthProvider sits OUTSIDE the router because `/signin` needs it too, and
 * outside AppProvider because identity outlives any single analysis -- a
 * `reset()` of the current upload must not touch who is signed in.
 *
 * DemoGate stays outermost of the two gates: a passphrase-protected deployment
 * has to let the caller past the passphrase before an account can even be
 * created, and DemoGate renders nothing at all when the backend is ungated,
 * which is every local run.
 */
// Each page is its own file, fetched the first time it is visited. The app
// used to ship as one 977 KB bundle, so the sign-in screen waited on the
// charting library the Analysis page uses. Vendor libraries are split out
// separately in vite.config.ts.
const Dashboard = lazyPage(() => import("./pages/Dashboard"));
const Analysis = lazyPage(() => import("./pages/Analysis"));
const UploadDeck = lazyPage(() => import("./pages/UploadDeck"));
const SignIn = lazyPage(() => import("./pages/SignIn"));
const NotFound = lazyPage(() => import("./pages/NotFound"));

// The same blank hold RequireAuth shows while it checks the session, so a page
// loading and a session being checked look identical: no spinner flash for
// what is normally a few tens of milliseconds.
function PageLoading({ children }: { children: ReactNode }) {
  return (
    <Suspense fallback={<div style={{ minHeight: "60vh" }} aria-busy="true" aria-label="Loading page" />}>
      {children}
    </Suspense>
  );
}

function App() {
  return (
    <AuthProvider>
      <AppProvider>
        <DemoGate>
          <BrowserRouter>
            <Routes>
              {/* Outside <Layout>: the sign-in screen is full-bleed and has no
                  sidebar, because there is nothing yet to navigate to. */}
              <Route path="/signin" element={<PageLoading><SignIn /></PageLoading>} />
              <Route
                path="*"
                element={
                  <Layout>
                    {/* Inside <Layout>, so the sidebar stays put while a page loads. */}
                    <PageLoading>
                      <Routes>
                        <Route path="/" element={<RequireAuth><Dashboard /></RequireAuth>} />
                        <Route path="/analysis" element={<RequireAuth><Analysis /></RequireAuth>} />
                        <Route path="/upload" element={<RequireAuth><UploadDeck /></RequireAuth>} />
                        <Route path="*" element={<NotFound />} />
                      </Routes>
                    </PageLoading>
                  </Layout>
                }
              />
            </Routes>
          </BrowserRouter>
        </DemoGate>
      </AppProvider>
    </AuthProvider>
  );
}

export default App;
