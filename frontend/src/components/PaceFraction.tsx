import { useUnits } from "../contexts/UnitsContext";

/**
 * Average pace rendered as a fraction — min/mi stacked over min/km,
 * separated by a rule:
 *
 *   8:30 /mi
 *   ────────
 *   5:17 /km
 *
 * Shrink-wraps its content (inline-flex), so it sits flush in
 * right-aligned or centered stat cells. Font size, weight and colour
 * are inherited from the parent; pass `className` to override.
 */
export function PaceFraction({
  sPerKm,
  className = "",
}: {
  sPerKm: number | null;
  className?: string;
}) {
  const { fmtPaceParts } = useUnits();
  if (!sPerKm) return <span className={className}>—</span>;
  const { mi, km } = fmtPaceParts(sPerKm);
  return (
    <span
      className={`inline-flex flex-col items-stretch text-center tabular-nums leading-tight ${className}`}
    >
      <span className="border-b border-gray-300 pb-px">{mi}</span>
      <span className="pt-px">{km}</span>
    </span>
  );
}
