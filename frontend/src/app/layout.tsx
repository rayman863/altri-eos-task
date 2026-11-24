import type { Metadata } from "next";
// Geist from the `geist` npm package (local font files via next/font/local), not
// next/font/google: the image build must not depend on reaching Google Fonts.
import { GeistMono } from "geist/font/mono";
import { GeistSans } from "geist/font/sans";
import "./globals.css";

export const metadata: Metadata = {
  title: "EOS Level 10",
  description: "Scorecard, Rocks, To-Dos, Issues and the weekly Level 10 Meeting.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${GeistSans.variable} ${GeistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">{children}</body>
    </html>
  );
}
