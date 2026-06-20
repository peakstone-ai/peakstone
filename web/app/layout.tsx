import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Peakstone — open-model capability benchmark",
  description:
    "A public, reproducible benchmark tracking the capability frontier of open models — high-water-mark stones for AI coding.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-stone-950 text-stone-100 antialiased">
        <header className="border-b border-stone-800">
          <nav className="mx-auto flex max-w-5xl items-center gap-6 px-4 py-3">
            <Link href="/" className="flex items-center gap-2 font-semibold">
              <span aria-hidden>🪨</span> Peakstone
            </Link>
            <div className="flex gap-4 text-sm text-stone-400">
              <Link href="/" className="hover:text-stone-100">Leaderboard</Link>
              <Link href="/challenges" className="hover:text-stone-100">Challenges</Link>
              <Link href="/proposals" className="hover:text-stone-100">Propose</Link>
              <Link href="/evolution" className="hover:text-stone-100">Evolution</Link>
              <Link href="/submit" className="hover:text-stone-100">Submit</Link>
            </div>
          </nav>
        </header>
        {children}
        <footer className="mx-auto max-w-5xl px-4 py-10 text-xs text-stone-600">
          Peakstone · reproducible, community-run · code Apache-2.0, data CC-BY-4.0
        </footer>
      </body>
    </html>
  );
}
