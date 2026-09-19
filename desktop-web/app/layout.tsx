import type { Metadata } from "next"
import "./globals.css"

export const metadata: Metadata = {
  title: "Jarvis",
  description: "Windows desktop shell — chat in the middle, Live Computer on the right.",
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" className="light h-full">
      <body className="h-full overflow-hidden bg-[#F8F9FB] font-[Segoe_UI,system-ui,sans-serif] text-[#111827] antialiased">
        {children}
      </body>
    </html>
  )
}
