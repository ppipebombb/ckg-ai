import { RequireAuth } from "@/components/auth/require-auth";
import { AppSidebar } from "@/components/sidebar/app-sidebar";
import { SidebarProvider } from "@/components/sidebar/sidebar-context";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <RequireAuth>
      <SidebarProvider>
        <div className="flex min-h-screen">
          <AppSidebar />
          <main className="flex-1 overflow-x-hidden">
            <div className="mx-auto max-w-7xl p-6">{children}</div>
          </main>
        </div>
      </SidebarProvider>
    </RequireAuth>
  );
}
