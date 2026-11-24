import type { Metadata, Viewport } from "next";
import {
  DM_Sans,
  JetBrains_Mono,
  Noto_Sans_Thai,
  Plus_Jakarta_Sans,
} from "next/font/google";
import type { ReactNode } from "react";
import { AppShell } from "@/components/AppShell";
import "./globals.css";

const plusJakarta = Plus_Jakarta_Sans({
  subsets: ["latin"],
  weight: ["500", "600", "700", "800"],
  variable: "--font-jakarta",
  display: "swap",
});

const dmSans = DM_Sans({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-dm",
  display: "swap",
});

const notoSansThai = Noto_Sans_Thai({
  subsets: ["thai"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-thai",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-jetbrains",
  display: "swap",
});

export const metadata: Metadata = {
  title: "ZYRQUEN Ω∞ · แพลตฟอร์ม AI ระหว่างพัฒนา",
  description:
    "ส่วนติดต่อเว็บและ API สำหรับแพลตฟอร์ม AI ระหว่างพัฒนา การอนุมาน Native Model ต้องมีการกำหนด model artifact",
  applicationName: "ZYRQUEN Ω∞",
  icons: { icon: "/zyrquen-icon.svg" },
};

export const viewport: Viewport = {
  themeColor: "#070b18",
  colorScheme: "dark",
};

export default function RootLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  const fontVars = [
    plusJakarta.variable,
    dmSans.variable,
    notoSansThai.variable,
    jetbrainsMono.variable,
  ].join(" ");

  return (
    <html className={fontVars} lang="th">
      <body>
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
