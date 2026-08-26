import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/layout/Layout";
import Dashboard from "./pages/Dashboard";
import Analysis from "./pages/Analysis";
import UploadDeck from "./pages/UploadDeck";
import NotFound from "./pages/NotFound";
import { AppProvider } from "./context/AppContext";
import DemoGate from "./components/common/DemoGate";

function App() {
  return (
    <AppProvider>
      {/* Wraps the whole app so a gated deployment asks for the passphrase
          before any page can call the API. Renders nothing when the backend
          is ungated, which is the case for every local run. */}
      <DemoGate>
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/analysis" element={<Analysis />} />
            <Route path="/upload" element={<UploadDeck />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Layout>
      </BrowserRouter>
      </DemoGate>
    </AppProvider>
  );
}

export default App;