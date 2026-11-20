import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { AppShell } from "@/components/AppShell";
import "./globals.css";

export const metadata: Metadata = {
  title: "ZYRQUEN Ω∞ · แพลตฟอร์มอัจฉริยะ",
  description:
    "แพลตฟอร์ม AI ที่พัฒนาขึ้นเพื่อให้คุณสามารถใช้งานระบบปัญญาประดิษฐ์ผ่านเครือข่ายออนไลน์ได้อย่างสะดวกและเป็นระบบ",
  applicationName: "ZYRQUEN Ω∞",
};

export const viewport: Viewport = {
  themeColor: "#080d13",
  colorScheme: "dark",
};

export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="th">
      <body><AppShell>{children}</AppShell></body>
    </html>
  );
}
