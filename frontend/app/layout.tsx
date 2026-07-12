import type { Metadata } from "next";
import "@fontsource/ibm-plex-sans/400.css";
import "@fontsource/ibm-plex-sans/500.css";
import "@fontsource/ibm-plex-sans/600.css";
import "@fontsource/ibm-plex-sans/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
import "./globals.css";
import { Toaster } from "@/components/toast";
import { GlossaryProvider } from "@/components/glossary-provider";

export const metadata: Metadata = {
  title: "Aletheia — 判断日志",
  description: "研究与判断支持系统",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>
        <GlossaryProvider>
          {children}
          <Toaster />
        </GlossaryProvider>
      </body>
    </html>
  );
}
