import type { Metadata } from "next";
import Link from "next/link";
import type { ReactNode } from "react";

import { LoginBox } from "@/components/LoginBox";
import { InstructorTokenProvider } from "@/lib/instructorToken";
import { UserProvider } from "@/lib/user";

import "./globals.css";

export const metadata: Metadata = {
  title: "CodeTutor",
  description: "CS1 Python practice with instant grading",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <UserProvider>
          <InstructorTokenProvider>
            <header className="site-header">
              <Link href="/" className="brand">
                CodeTutor
              </Link>
              <Link href="/demo">Teacher demo</Link>
              <Link href="/instructor">Instructor</Link>
              <LoginBox />
            </header>
            <main>{children}</main>
          </InstructorTokenProvider>
        </UserProvider>
      </body>
    </html>
  );
}
