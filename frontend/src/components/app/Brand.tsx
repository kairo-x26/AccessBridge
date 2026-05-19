/** The mark: a short route segment with a stop, the product's core image. */
export function BrandMark({ size = 28 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 28 28" aria-hidden="true">
      <path d="M4 20 C 10 20, 10 8, 16 8 L 24 8" fill="none" stroke="var(--route)" strokeWidth="4" strokeLinecap="round" />
      <circle cx="4" cy="20" r="3.5" fill="var(--route)" />
      <circle cx="24" cy="8" r="4.5" fill="var(--surface)" stroke="var(--route)" strokeWidth="3" />
    </svg>
  );
}
