import type { Metadata } from "next"
import "./globals.css"
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "工厂管理平台",
  description: "原料药制药厂综合业务管理平台",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="zh-CN" className={cn("h-full", "font-sans")}>
      <body className="h-full antialiased">{children}</body>
    </html>
  )
}
