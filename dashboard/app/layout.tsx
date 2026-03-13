import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Autoresearch Dashboard - Polymarket Calibration",
  description:
    "Autonomous learning loop results: 50 iterations of per-category calibration tuning across 180K Polymarket markets",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-zinc-950 text-zinc-100`}
      >
        <header className="border-b border-zinc-800 bg-zinc-950/80 backdrop-blur-sm sticky top-0 z-50">
          <div className="mx-auto max-w-7xl px-6 py-4 flex items-center justify-between">
            <div>
              <h1 className="text-lg font-semibold text-white">
                Autoresearch Dashboard
              </h1>
              <p className="text-sm text-zinc-500">
                Polymarket Calibration -- 180K markets, 50 iterations
              </p>
            </div>
            <span className="text-xs text-zinc-600 font-mono">v1.0</span>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
