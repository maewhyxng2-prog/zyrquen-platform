import type { HTMLAttributes, ReactNode } from "react";

export function Panel({
  children,
  className = "",
  ...rest
}: {
  children: ReactNode;
  className?: string;
} & HTMLAttributes<HTMLElement>) {
  return (
    <section className={`panel ${className}`} {...rest}>
      {children}
    </section>
  );
}
