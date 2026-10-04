import { motion, useReducedMotion, useSpring } from "motion/react";
import { useRef, type ComponentProps } from "react";

type Props = ComponentProps<typeof motion.button> & { strength?: number };

export function MagneticButton({ strength = 0.25, children, style, ...props }: Props) {
  const ref = useRef<HTMLButtonElement>(null);
  const reduced = useReducedMotion();
  const x = useSpring(0, { stiffness: 300, damping: 20 });
  const y = useSpring(0, { stiffness: 300, damping: 20 });
  return (
    <motion.button
      whileTap={{ scale: 0.96 }}
      {...props}
      ref={ref}
      style={{ x, y, ...style }}
      onPointerMove={(e) => {
        props.onPointerMove?.(e);
        const r = ref.current?.getBoundingClientRect();
        if (!r || reduced) return;
        x.set((e.clientX - (r.left + r.width / 2)) * strength);
        y.set((e.clientY - (r.top + r.height / 2)) * strength);
      }}
      onPointerLeave={(e) => {
        props.onPointerLeave?.(e);
        x.set(0);
        y.set(0);
      }}
    >
      {children}
    </motion.button>
  );
}
