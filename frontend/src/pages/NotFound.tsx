import { useNavigate } from "react-router-dom";
import { Compass } from "lucide-react";

// Previously there was no catch-all route, so an unknown path rendered the
// sidebar with a blank main panel (QA-006). This gives it an explicit page
// and a way back instead of a silent dead end.
const NotFound = () => {
  const navigate = useNavigate();
  return (
    <div style={{
      display: "flex", flexDirection: "column", alignItems: "center",
      justifyContent: "center", minHeight: "60vh", textAlign: "center",
      padding: "40px 24px", fontFamily: "var(--font-sans)",
    }}>
      <div style={{
        width: 64, height: 64, borderRadius: 18,
        background: "rgba(29,111,232,0.08)", border: "1px solid rgba(29,111,232,0.18)",
        display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 20,
      }}>
        <Compass size={28} color="#1D6FE8" strokeWidth={1.5} />
      </div>
      <div style={{ fontFamily: "var(--font-display)", fontSize: 22, marginBottom: 8, color: "#0B1120" }}>
        Page not found
      </div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "#5D6B7F", marginBottom: 24, maxWidth: 320 }}>
        There's nothing at this address. Head back to the dashboard to keep working.
      </div>
      <button onClick={() => navigate("/")} style={{
        display: "inline-flex", alignItems: "center", gap: 8,
        background: "#1D6FE8", color: "#fff", border: "none",
        borderRadius: 10, padding: "11px 22px", fontFamily: "var(--font-sans)",
        fontSize: 14, fontWeight: 600, cursor: "pointer",
      }}>
        Back to dashboard
      </button>
    </div>
  );
};

export default NotFound;
