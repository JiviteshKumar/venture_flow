import Sidebar from "./Sidebar";

/**
 * App shell.
 *
 * The colours and font stack here used to be raw literals — `#F2F2F7`,
 * `#1C1C1E`, and a `'Geist', 'Inter', …` stack naming two fonts the app never
 * loaded, so it silently fell through to the system default anyway. They now
 * reference the shared tokens in src/styles/tailwind.css, which is the same
 * set tailwind.config.js exposes.
 *
 * `min-w-0` on <main> is load-bearing: a flex child defaults to
 * `min-width: auto`, which refuses to shrink below its content's intrinsic
 * width. Without it a wide table inside a page pushes the whole shell sideways
 * instead of scrolling within its own container, which is what made the app
 * scroll horizontally on narrow viewports.
 */
const Layout = ({ children }: { children: React.ReactNode }) => {
  return (
    <div className="flex h-screen overflow-hidden bg-canvas text-ink font-sans">
      <Sidebar />
      <main
        className="relative min-w-0 flex-1 overflow-y-auto bg-canvas"
        style={{ scrollbarWidth: "none" }}
      >
        <div className="relative z-[1]">{children}</div>
      </main>
    </div>
  );
};

export default Layout;
