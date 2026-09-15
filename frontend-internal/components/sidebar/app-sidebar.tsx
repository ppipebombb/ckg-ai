"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  Baby,
  Bot,
  BookOpen,
  Calculator,
  ChevronDown,
  ChevronsLeft,
  ChevronsRight,
  Clock,
  Cpu,
  Droplet,
  Droplets,
  GitCompareArrows,
  GraduationCap,
  HeartPulse,
  LayoutDashboard,
  LogOut,
  PhoneCall,
  PieChart,
  PlayCircle,
  Receipt,
  RefreshCw,
  Sparkles,
  Stethoscope,
  TestTube,
  Weight,
} from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useAdminMe, useLogout } from "@/lib/hooks/use-auth";
import { useSidebar } from "./sidebar-context";
import type { LucideIcon } from "lucide-react";

type NavItem = { href: string; label: string; icon: LucideIcon };
type NavGroup = { group: string; icon: LucideIcon; children: NavItem[] };
type NavEntry = NavItem | NavGroup;

function isGroup(entry: NavEntry): entry is NavGroup {
  return "group" in entry;
}

function matches(href: string, pathname: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * Which child of a group is the active one: the LONGEST matching href. A parent
 * route can be a prefix of its own sub-page (/hipertensi-report is a prefix of
 * /hipertensi-report/gap-tatalaksana), and a plain prefix test would light up
 * both. Returns null when the group holds nothing for this path.
 */
function activeChildHref(children: NavItem[], pathname: string): string | null {
  let best: string | null = null;
  for (const c of children) {
    if (matches(c.href, pathname) && (best === null || c.href.length > best.length))
      best = c.href;
  }
  return best;
}

const NAV: NavEntry[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  {
    group: "Patients",
    icon: HeartPulse,
    children: [
      { href: "/patients", label: "CKG Umum", icon: HeartPulse },
      { href: "/school-patients", label: "CKG Sekolah", icon: GraduationCap },
    ],
  },
  { href: "/puskesmas", label: "Puskesmas", icon: Stethoscope },
  // { href: "/users", label: "Users", icon: Users },
  {
    group: "LLM",
    icon: Cpu,
    children: [
      { href: "/llm-configs", label: "Konfigurasi LLM", icon: Cpu },
      { href: "/llm-logs", label: "Log LLM", icon: Receipt },
    ],
  },
  {
    group: "Referensi",
    icon: BookOpen,
    children: [
      { href: "/calculator", label: "Kalkulator", icon: Calculator },
      { href: "/mapping-reference", label: "Referensi Pemetaan", icon: BookOpen },
      { href: "/visit-summary", label: "Ringkasan Kunjungan", icon: PieChart },
    ],
  },
  {
    group: "Jobs",
    icon: PlayCircle,
    children: [
      { href: "/scrape-jobs", label: "Scrape Jobs", icon: PlayCircle },
      { href: "/sync-jobs", label: "Sync Jobs", icon: RefreshCw },
      { href: "/merge-with-ai", label: "Merge With AI", icon: Sparkles },
      { href: "/loop-runs", label: "Loop Agent", icon: Bot },
    ],
  },
  { href: "/merge-conflicts", label: "Conflict Analysis", icon: GitCompareArrows },
  { href: "/cron-runs", label: "Cron Runs", icon: Clock },
  { href: "/gdp-report", label: "Kertas Kerja DM Terkendali", icon: Droplet },
  // The four dirjen registries, in the same order the client dashboard lists
  // them. Both apps render the SAME shared view (frontend-shared/<resource>/
  // components/*-registry-view.tsx); the only difference is that internal passes
  // showClearCache so an admin can force a cache rebuild.
  {
    group: "Kertas Kerja Hipertensi",
    icon: Activity,
    children: [
      { href: "/hipertensi-report", label: "Kertas Kerja Hipertensi", icon: Activity },
      {
        href: "/hipertensi-report/gap-tatalaksana",
        label: "Gap Tatalaksana",
        icon: PhoneCall,
      },
    ],
  },
  { href: "/dm-report", label: "Kertas Kerja Diabetes Melitus", icon: Droplets },
  { href: "/lipid-report", label: "Kertas Kerja Dislipidemia", icon: TestTube },
  { href: "/obesitas-report", label: "Kertas Kerja Obesitas", icon: Weight },
  // Registri bayi baru lahir (PJB-K). PJBK sheet joins the dropdown once its
  // page is built; the two Bayi Kuning (ikterus) sheets are live now.
  {
    group: "Registri PJB-K",
    icon: Baby,
    children: [
      { href: "/bayi-kuning-ikterus", label: "Bayi Kuning - Ikterus", icon: Baby },
      {
        href: "/bayi-kuning-ikterus-berat",
        label: "Bayi Kuning - Ikterus Berat",
        icon: Baby,
      },
    ],
  },
];

export function AppSidebar() {
  const { collapsed, toggle } = useSidebar();
  const pathname = usePathname();
  const me = useAdminMe(true);
  const logout = useLogout();
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>(() => {
    const init: Record<string, boolean> = {};
    for (const entry of NAV) {
      if (isGroup(entry)) {
        init[entry.group] = activeChildHref(entry.children, pathname) !== null;
      }
    }
    return init;
  });

  return (
    <aside
      className={cn(
        "sticky top-0 flex h-screen flex-col border-r border-[var(--sidebar-border)] bg-[var(--sidebar)] text-[var(--sidebar-foreground)] transition-[width] duration-150",
        collapsed ? "w-14" : "w-60",
      )}
    >
      <div
        className={cn(
          "flex h-14 items-center border-b border-[var(--sidebar-border)]",
          collapsed ? "justify-center px-2" : "justify-between px-4",
        )}
      >
        {!collapsed && (
          <span className="text-sm font-semibold tracking-tight">CKG Admin</span>
        )}
        <Button
          variant="ghost"
          size="icon"
          onClick={toggle}
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          className="h-8 w-8"
        >
          {collapsed ? (
            <ChevronsRight className="h-4 w-4" />
          ) : (
            <ChevronsLeft className="h-4 w-4" />
          )}
        </Button>
      </div>

      <nav className="flex-1 space-y-1 p-2">
        {NAV.map((entry) => {
          if (isGroup(entry)) {
            const Icon = entry.icon;
            const activeHref = activeChildHref(entry.children, pathname);
            const anyChildActive = activeHref !== null;

            if (collapsed) {
              return (
                <Link
                  key={entry.group}
                  href={entry.children[0].href}
                  prefetch={false}
                  title={entry.group}
                  className={cn(
                    "flex items-center justify-center rounded-md px-2 py-2 text-sm transition-colors",
                    anyChildActive
                      ? "bg-[var(--sidebar-accent)] text-[var(--sidebar-accent-foreground)] font-medium"
                      : "text-[var(--sidebar-foreground)] hover:bg-[var(--sidebar-accent)]/60",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                </Link>
              );
            }

            const isOpen = openGroups[entry.group] ?? false;
            return (
              <div key={entry.group}>
                <button
                  onClick={() =>
                    setOpenGroups((o) => ({ ...o, [entry.group]: !o[entry.group] }))
                  }
                  className={cn(
                    "flex w-full items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                    anyChildActive
                      ? "bg-[var(--sidebar-accent)] text-[var(--sidebar-accent-foreground)] font-medium"
                      : "text-[var(--sidebar-foreground)] hover:bg-[var(--sidebar-accent)]/60",
                  )}
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className="flex-1 truncate text-left">{entry.group}</span>
                  <ChevronDown
                    className={cn(
                      "h-3.5 w-3.5 shrink-0 transition-transform duration-150",
                      isOpen && "rotate-180",
                    )}
                  />
                </button>
                {isOpen && (
                  <div className="mt-1 space-y-1 pl-4">
                    {entry.children.map((child) => {
                      const ChildIcon = child.icon;
                      const active = child.href === activeHref;
                      return (
                        <Link
                          key={child.href}
                          href={child.href}
                          prefetch={false}
                          className={cn(
                            "flex items-center gap-3 rounded-md px-3 py-1.5 text-sm transition-colors",
                            active
                              ? "bg-[var(--sidebar-accent)] text-[var(--sidebar-accent-foreground)] font-medium"
                              : "text-[var(--sidebar-foreground)] hover:bg-[var(--sidebar-accent)]/60",
                          )}
                        >
                          <ChildIcon className="h-3.5 w-3.5 shrink-0" />
                          <span className="truncate">{child.label}</span>
                        </Link>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          }

          const Icon = entry.icon;
          const active =
            pathname === entry.href || pathname.startsWith(`${entry.href}/`);
          return (
            <Link
              key={entry.href}
              href={entry.href}
              prefetch={false}
              className={cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-[var(--sidebar-accent)] text-[var(--sidebar-accent-foreground)] font-medium"
                  : "text-[var(--sidebar-foreground)] hover:bg-[var(--sidebar-accent)]/60",
                collapsed && "justify-center px-2",
              )}
              title={collapsed ? entry.label : undefined}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!collapsed && <span className="truncate">{entry.label}</span>}
            </Link>
          );
        })}
      </nav>

      <div
        className={cn(
          "border-t border-[var(--sidebar-border)] p-3",
          collapsed && "p-2",
        )}
      >
        {!collapsed ? (
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <p className="truncate text-xs font-medium">
                {me.data?.full_name ?? "—"}
              </p>
              <p className="truncate text-xs text-[var(--muted-foreground)]">
                {me.data?.email ?? ""}
              </p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={logout}
              aria-label="Sign out"
              className="h-8 w-8"
            >
              <LogOut className="h-4 w-4" />
            </Button>
          </div>
        ) : (
          <Button
            variant="ghost"
            size="icon"
            onClick={logout}
            aria-label="Sign out"
            className="mx-auto flex h-8 w-8"
          >
            <LogOut className="h-4 w-4" />
          </Button>
        )}
      </div>
    </aside>
  );
}
