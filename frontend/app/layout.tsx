import type { Metadata } from "next";
import { AppShell, DashboardProvider } from "@/components/regops";
import "./globals.css";

export const metadata: Metadata = {
  title: "RegOps | AI Agent Compliance",
  description: "CI/CD for AI-agent compliance",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body><DashboardProvider><AppShell>{children}</AppShell></DashboardProvider></body>
    </html>
  );
}
