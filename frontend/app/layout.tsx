import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RegOps Control Room",
  description: "CI/CD for AI-agent compliance",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
