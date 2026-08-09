import type { Direction } from "@/lib/types";

export function Sparkline({ values, direction }: { values: number[]; direction: Direction }) {
  if (!values || values.length < 2) return null;

  const width = 240;
  const height = 48;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const points = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width;
      const y = height - 4 - ((v - min) / range) * (height - 8);
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="sparkline" preserveAspectRatio="none">
      <polyline points={points} fill="none" className={`sparkline-line ${direction}`} />
    </svg>
  );
}
