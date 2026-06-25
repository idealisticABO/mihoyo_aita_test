import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Blender Pipeline Studio",
  description: "Blender → ComfyUI → Texture reconstruction pipeline",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body className="min-h-screen flex flex-col">
        <header className="border-b border-ink-600 bg-ink-900/80 backdrop-blur sticky top-0 z-10">
          <div className="max-w-6xl mx-auto px-6 py-3 flex items-center justify-between">
            <Link href="/" className="text-lg font-semibold tracking-tight">
              <span className="text-accent-400">●</span> Blender Pipeline Studio
            </Link>
            <nav className="flex gap-4 text-sm text-slate-300">
              <Link href="/" className="hover:text-white">Dashboard</Link>
              <Link href="/tasks/new" className="hover:text-white">新建任务</Link>
              <Link href="/config" className="hover:text-white">配置</Link>
            </nav>
          </div>
        </header>
        <main className="flex-1 max-w-6xl w-full mx-auto px-6 py-8">{children}</main>
        <footer className="border-t border-ink-600 text-xs text-slate-500 text-center py-3">
          v0.1.0 · local-first
        </footer>
      </body>
    </html>
  );
}
