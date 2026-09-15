import { redirect } from "next/navigation";

// The Dashboard tab is a dropdown (Hipertensi / Diabetes Melitus); /dashboard
// itself has no content — land on the first subtab.
export default function DashboardPage() {
  redirect("/dashboard/hipertensi");
}
