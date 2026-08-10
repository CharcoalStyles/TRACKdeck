import { useRef } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { useLogout } from "../../hooks/useAuth";

const ADMIN_PATHS = [
  "/settings",
  "/admin/testing",
  "/admin/checkins",
  "/admin/alert-sounds",
  "/admin/errors",
  "/admin/thread-debug",
  "/vault",
  "/projects",
];

const navLinkClass = ({ isActive }: { isActive: boolean }) =>
  `px-1 pb-0.5 ${isActive ? "border-b-2 border-accent text-accent" : "text-text-primary hover:text-accent"}`;

export default function AppShell() {
  const logout = useLogout();
  const location = useLocation();
  const mobileMenuRef = useRef<HTMLDetailsElement>(null);
  const isMobileActive = ADMIN_PATHS.some((p) =>
    location.pathname.startsWith(p),
  );

  return (
    <div className="flex flex-col h-dvh bg-base text-text-primary">
      <header className="flex flex-wrap h-14 items-center gap-4 border-b border-border bg-header px-4 py-3">
        <h1 className="text-lg font-semibold">TRACKdeck</h1>
        <nav className="flex flex-wrap grow items-center gap-4 text-sm">
          <div className="md:flex flex-wrap grow hidden gap-4">
            <MainNav />
            <AdminNav />
          </div>
          <div className="flex grow md:hidden flex-wrap gap-4">
            <details
              ref={mobileMenuRef}
              className="relative"
              onClick={(e) => {
                if ((e.target as HTMLElement).closest("a"))
                  mobileMenuRef.current?.removeAttribute("open");
              }}>
              <summary
                className={`cursor-pointer list-none px-1 pb-0.5 ${isMobileActive ? "border-b-2 border-accent text-accent" : "text-text-primary hover:text-accent"}`}>
                Menu
              </summary>
              <div className="absolute left-0 z-10 mt-2 flex w-44 flex-col gap-1 rounded border border-border bg-card p-2 shadow-lg">
                <MainNav />
              </div>
            </details>
            <AdminNav />
          </div>
          <a
            href="#"
            onClick={(e) => {
              e.preventDefault();
              logout.mutate();
            }}
            className="px-1 pb-0.5 text-text-primary hover:text-accent">
            Log out
          </a>
        </nav>
      </header>
      <main className="p-4 flex flex-1 min-h-0 overflow-y-auto ">
        <Outlet />
      </main>
    </div>
  );
}

const MainNav = () => {
  return (
    <>
      <NavLink to="/" end className={navLinkClass}>
        Chat
      </NavLink>
      <NavLink to="/activity-log" className={navLinkClass}>
        Activity Log
      </NavLink>
      <NavLink to="/reminders" className={navLinkClass}>
        To-Dos
      </NavLink>
      <NavLink to="/projects" className={navLinkClass}>
        Projects
      </NavLink>
      <NavLink to="/profile" className={navLinkClass}>
        Profile
      </NavLink>
    </>
  );
};

const AdminNav = () => {
  const location = useLocation();
  const adminMenuRef = useRef<HTMLDetailsElement>(null);
  const isAdminActive = ADMIN_PATHS.some((p) =>
    location.pathname.startsWith(p),
  );
  return (
    <details
      ref={adminMenuRef}
      className="relative"
      onClick={(e) => {
        if ((e.target as HTMLElement).closest("a"))
          adminMenuRef.current?.removeAttribute("open");
      }}>
      <summary
        className={`cursor-pointer list-none px-1 pb-0.5 ${isAdminActive ? "border-b-2 border-accent text-accent" : "text-text-primary hover:text-accent"}`}>
        Admin
      </summary>
      <div className="absolute left-0 z-10 mt-2 flex w-44 flex-col gap-1 rounded border border-border bg-card p-2 shadow-lg">
        <NavLink to="/settings" className={navLinkClass}>
          Settings
        </NavLink>
        <NavLink to="/admin/testing" className={navLinkClass}>
          Testing
        </NavLink>
        <NavLink to="/admin/checkins" className={navLinkClass}>
          Check-Ins
        </NavLink>
        <NavLink to="/admin/alert-sounds" className={navLinkClass}>
          Alert Sounds
        </NavLink>
        <NavLink to="/admin/errors" className={navLinkClass}>
          Errors
        </NavLink>
        <NavLink to="/admin/thread-debug" className={navLinkClass}>
          Thread Debug
        </NavLink>
        <NavLink to="/vault" className={navLinkClass}>
          Vault
        </NavLink>
        <a
          href="/calendar/"
          target="_blank"
          rel="noopener"
          title="Manage calendars (create/rename/delete) — to view or edit events, use a CalDAV app like Thunderbird or your phone's calendar"
          className="px-1 pb-0.5 text-text-primary hover:text-accent">
          Calendar
        </a>
      </div>
    </details>
  );
};
