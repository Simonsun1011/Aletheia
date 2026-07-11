import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Aletheia — 判断日志",
  description: "Slice 1: judgment loop",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
