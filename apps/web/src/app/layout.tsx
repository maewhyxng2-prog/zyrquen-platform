import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";
import { AppShell } from "@/components/AppShell";
import "./globals.css";

export const metadata: Metadata = {
  title: "ZYRQUEN Ω∞ · แพลตฟอร์ม AI ระหว่างพัฒนา",
  description:
    "ส่วนติดต่อเว็บและ API สำหรับแพลตฟอร์ม AI ระหว่างพัฒนา การอนุมาน Native Model ต้องมีการกำหนด model artifact",
  applicationName: "ZYRQUEN Ω∞",
  icons: { icon: "/zyrquen-icon.svg" },
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
