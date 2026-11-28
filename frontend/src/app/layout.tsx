import type { Metadata } from "next";
import { connection } from "next/server";
// Geist from the `geist` npm package (local font files via next/font/local), not
// next/font/google: the image build must not depend on reaching Google Fonts.
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import "./globals.css";

import { TooltipProvider } from "@/components/ui/tooltip";

export const metadata: Metadata = {
  title: "EOS Level 10",
  description: "Scorecard, Rocks, To-Dos, Issues and the weekly Level 10 Meeting.",
};

// Every page renders per request (never prerendered at build time): the nonce CSP (proxy.ts)
// needs a fresh nonce on each response, and a prerendered page would carry none, so its
// scripts would be blocked.
export default async function RootLayout({ children }: LayoutProps<"/">) {
  await connection();
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <TooltipProvider>{children}</TooltipProvider>
      </body>
    </html>
  );
}
