import { useLocation } from "react-router-dom";
import Sidebar from "./Sidebar";

/**
 * App shell.
 *
 * TWO SHELLS, NOT ONE
 *
 * The working screens -- the list of analyses and the upload form -- are
 * tools, and tools want their navigation permanently to hand: a sidebar, a
 * light canvas, dense controls.
 *
 * The report is not a tool. It is the thing the tool produced, and it is read
 * rather than operated. Every reference this was rebuilt against (a building,
 * a property collection, a campaign) does the same thing: the piece owns the
 * whole viewport and the chrome gets out of the way. Keeping a 252px sidebar
 * and a grey page behind it is what made the previous pass read as a dashboard
 * with big type rather than as a document.
 *
 * So `/analysis` renders full-bleed on its own dark ground, with navigation
 * reduced to one floating control the report itself draws. Everything else
 * keeps the shell.
 *
 * `min-w-0` on <main> is load-bearing: a flex child defaults to
 * `min-width: auto`, which refuses to shrink below its content's intrinsic
 * width. Without it a wide table inside a page pushes the whole shell sideways
 * instead of scrolling within its own container, which is what made the app
 * scroll horizontally on narrow viewports.
 */
const Layout = ({ children }: { children: React.ReactNode }) => {
  const { pathname } = useLocation();
  // Upload and the report are scenes; the deal table is a tool. See tokens.css
  // for what the two modes mean and why they are not two design systems.
  const cinematic = pathname.startsWith("/analysis") || pathname.startsWith("/upload");

  if (cinematic) {
    return (
      <div className="h-screen overflow-hidden" data-mode="cinematic" style={{ background: "transparent" }}>
        <main
          id="vf-scroller"
          className="relative h-full w-full overflow-y-auto"
          style={{ scrollbarWidth: "none", background: "transparent" }}
        >
          {children}
        </main>
      </div>
    );
  }

  return (
    <div
      className="flex h-screen overflow-hidden font-sans"
      data-mode="analytical"
      style={{ background: "transparent", color: "var(--text)" }}
    >
      <Sidebar />
      <main
        id="vf-scroller"
        className="relative min-w-0 flex-1 overflow-y-auto"
        style={{ scrollbarWidth: "none", background: "transparent" }}
      >
        <div className="relative z-[1]">{children}</div>
      </main>
    </div>
  );
};

export default Layout;
