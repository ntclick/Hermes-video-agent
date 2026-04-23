import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Content Bridge — Hermes Agent Dashboard',
  description: 'Autonomous video translation and publishing pipeline powered by Hermes Agent, Kimi K2.5, and FFmpeg',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
