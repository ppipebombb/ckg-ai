import { RequireAuth } from "@/components/auth/require-auth";
import { ChatWidget } from "@/components/chatbot/chat-widget";
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
            {/* pb-28 reserves clearance for the fixed ChatWidget FAB
                (bottom-6 + h-14 ≈ 80px) so bottom-right content like
                pagination never scrolls under it. */}
            <div className="mx-auto max-w-7xl p-6 pb-28">{children}</div>
          </main>
          {/* Mounted once inside the authed shell — never renders on /login. */}
          <ChatWidget />
        </div>
      </SidebarProvider>
    </RequireAuth>
  );
}
