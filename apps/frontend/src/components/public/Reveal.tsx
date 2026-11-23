"use client";

// #961: scroll-reveal wrapper for the homepage sections, matching the
// prototype's IntersectionObserver `.reveal` motion. The observer only
// reveals - never hides - so a section can never get stuck invisible:
// - no IntersectionObserver support (jsdom, old engines) -> visible at once
// - prefers-reduced-motion / scripting:none -> CSS forces the visible state
// - once revealed the observer disconnects

import { useEffect, useRef, useState, type ReactNode } from "react";

import { cn } from "@/lib/utils";

const REVEAL_ROOT_MARGIN = "0px 0px -6% 0px";
const REVEAL_THRESHOLD = 0.05;

interface RevealProps {
  children: ReactNode;
}

export function Reveal({ children }: RevealProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setVisible(true);
            observer.disconnect();
          }
        }
      },
      { rootMargin: REVEAL_ROOT_MARGIN, threshold: REVEAL_THRESHOLD },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div ref={ref} className={cn("reveal", visible && "in")}>
      {children}
    </div>
  );
}
