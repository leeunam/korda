import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
  weight: ["400", "600", "700"],
});

const jetbrains = JetBrains_Mono({
  variable: "--font-jetbrains",
  subsets: ["latin"],
  weight: ["400", "500"],
});

export const metadata: Metadata = {
  title: "Korda",
  description: "Follow a run of Theseus (Executor Agent).",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  // Tema escuro fixo: data-theme="dark" ativa os tokens escuros de globals.css.
  return (
    <html lang="en" data-theme="dark" className={`${inter.variable} ${jetbrains.variable} h-full antialiased`}>
      <body className="min-h-full flex flex-col font-sans">{children}</body>
    </html>
  );
}
