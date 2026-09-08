import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/layout/Layout";
import Dashboard from "./pages/Dashboard";
import Analysis from "./pages/Analysis";
import UploadDeck from "./pages/UploadDeck";
import SignIn from "./pages/SignIn";
import NotFound from "./pages/NotFound";
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
function App() {
  return (
    <AuthProvider>
      <AppProvider>
        <DemoGate>
          <BrowserRouter>
            <Routes>
              {/* Outside <Layout>: the sign-in screen is full-bleed and has no
                  sidebar, because there is nothing yet to navigate to. */}
              <Route path="/signin" element={<SignIn />} />
              <Route
                path="*"
                element={
                  <Layout>
                    <Routes>
                      <Route path="/" element={<RequireAuth><Dashboard /></RequireAuth>} />
                      <Route path="/analysis" element={<RequireAuth><Analysis /></RequireAuth>} />
                      <Route path="/upload" element={<RequireAuth><UploadDeck /></RequireAuth>} />
                      <Route path="*" element={<NotFound />} />
                    </Routes>
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
