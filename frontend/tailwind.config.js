export default {
    content: ["./index.html", "./src/**/*.{ts,tsx}"],
    theme: {
      extend: {
        colors: {
          // 🌑 Base surfaces
          background: "#0b0f1a",   // main app bg (matches sidebar vibe)
          card: "#0f172a",         // solid card (NO transparency)
          surface: "#111827",      // optional secondary surface
  
          // 🧊 Borders & subtle UI
          border: "rgba(255,255,255,0.08)",
          muted: "#1f2937",
  
          // 📝 Text hierarchy
          text: {
            primary: "#ffffff",
            secondary: "#9ca3af",
            muted: "#6b7280",
          },
  
          // 🎯 Brand (your sidebar purple)
          primary: "#8b5cf6",
          primaryHover: "#7c3aed",
          primarySoft: "rgba(139,92,246,0.12)",
        },
  
        boxShadow: {
          // soft depth (Vercel style)
          soft: "0 10px 30px rgba(0,0,0,0.4)",
          card: "0 20px 60px rgba(0,0,0,0.5)",
  
          // subtle purple glow (only for highlights)
          glow: "0 0 30px rgba(139,92,246,0.25)",
        },
  
        backdropBlur: {
          glass: "12px",
        },
  
        borderRadius: {
          xl: "12px",
          "2xl": "16px",
        },
      },
    },
    plugins: [],
  };