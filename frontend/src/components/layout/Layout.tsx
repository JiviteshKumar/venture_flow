import Sidebar from "./Sidebar";

const Layout = ({ children }: any) => {
  return (
    <div style={{
      display: "flex",
      height: "100vh",
      background: "#F2F2F7",
      color: "#1C1C1E",
      overflow: "hidden",
      fontFamily: "'Geist', 'Inter', -apple-system, BlinkMacSystemFont, sans-serif",
    }}>
      <Sidebar />
      <main style={{
        flex: 1,
        overflowY: "auto",
        background: "#F2F2F7",
        position: "relative",
        scrollbarWidth: "none",
      }}>
        <div style={{ position: "relative", zIndex: 1 }}>
          {children}
        </div>
      </main>
    </div>
  );
};

export default Layout;
