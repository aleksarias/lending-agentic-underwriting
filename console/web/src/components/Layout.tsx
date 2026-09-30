/** App shell: grouped sidebar navigation, status bar, routed content, Ask drawer. */
import { Suspense, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useStatus } from "../api/hooks";
import { NAV } from "../routes";
import { AskDrawer } from "./AskDrawer";
import { StatusBar } from "./StatusBar";
import { Loading } from "./ui";

export function Layout() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [askOpen, setAskOpen] = useState(false);
  const status = useStatus();
  const loc = useLocation();
  const counts = {
    decisions_waiting: status.data?.decisions_waiting ?? 0,
    alerts_open: (status.data?.alerts_open.high ?? 0) + (status.data?.alerts_open.medium ?? 0),
  };
  return (
    <div className="shell">
      <nav className={`sidebar ${menuOpen ? "open" : ""}`} aria-label="Main navigation" onClick={() => setMenuOpen(false)}>
        <div className="brand">
          <span className="name">Underwriting Console</span>
          <span className="sub">Agents propose · harness judges · people approve</span>
        </div>
        {NAV.map((g) => (
          <div className="nav-group" key={g.label}>
            <div className="label">{g.label}</div>
            {g.items.map((it) => (
              <NavLink key={it.path} to={it.path} end={it.path === "/"} className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
                <span>{it.label}</span>
                {it.countKey && counts[it.countKey] > 0 && <span className="count">{counts[it.countKey]}</span>}
              </NavLink>
            ))}
          </div>
        ))}
      </nav>
      <div className="main">
        <StatusBar onMenu={() => setMenuOpen((o) => !o)} onAsk={() => setAskOpen(true)} />
        <main className="content" key={loc.pathname}>
          <Suspense fallback={<Loading height={240} />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
      {askOpen && <AskDrawer onClose={() => setAskOpen(false)} />}
    </div>
  );
}
