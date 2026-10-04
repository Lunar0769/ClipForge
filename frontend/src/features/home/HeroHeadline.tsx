import { useGSAP } from "@gsap/react";
import { gsap } from "gsap";
import { SplitText } from "gsap/SplitText";
import { useRef } from "react";

gsap.registerPlugin(SplitText, useGSAP);

export function HeroHeadline() {
  const ref = useRef<HTMLHeadingElement>(null);

  useGSAP(
    () => {
      if (!ref.current || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
      const split = SplitText.create(ref.current.querySelector("[data-split]"), { type: "chars", mask: "chars" });
      gsap.from(split.chars, { yPercent: 110, duration: 0.9, ease: "expo.out", stagger: 0.02 });
      gsap.from(ref.current.querySelector("[data-glow]"), {
        y: 24, opacity: 0, filter: "blur(12px)", duration: 1.1, ease: "expo.out", delay: 0.35,
      });
      return () => split.revert();
    },
    { scope: ref },
  );

  return (
    <h1 ref={ref} className="font-display text-5xl font-semibold leading-[1.02] tracking-tight text-balance sm:text-7xl">
      <span data-split className="block">Long videos in.</span>
      <span data-glow className="block text-gradient">Viral shorts out.</span>
    </h1>
  );
}
