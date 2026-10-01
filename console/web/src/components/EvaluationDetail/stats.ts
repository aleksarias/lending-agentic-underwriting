/** Wilson score interval for a binomial proportion (95% by default): observed rate `p` from `n` loans. */
export function wilson(p: number, n: number, z = 1.959964): { lo: number; hi: number } | null {
  if (!Number.isFinite(p) || !Number.isFinite(n) || n <= 0) return null;
  const z2 = z * z;
  const denom = 1 + z2 / n;
  const centre = (p + z2 / (2 * n)) / denom;
  const half = (z * Math.sqrt((p * (1 - p)) / n + z2 / (4 * n * n))) / denom;
  return { lo: Math.max(0, centre - half), hi: Math.min(1, centre + half) };
}

/** Round axis ticks (1, 2, 2.5 or 5 times a power of ten) from at or below `lo` to the first tick at or above `hi`. */
export function niceTicks(lo: number, hi: number, target = 5): { ticks: number[]; step: number; digits: number } {
  const span = hi - lo || 1;
  const raw = span / (target - 1);
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  const step = [1, 2, 2.5, 5, 10].map((k) => k * pow).find((v) => v >= raw) ?? raw;
  const first = Math.floor(lo / step + 1e-9) * step;
  const ticks: number[] = [];
  for (let v = first; ticks.length < 50; v += step) {
    ticks.push(Number(v.toFixed(10)));
    if (v >= hi - step * 1e-9) break;
  }
  return { ticks, step, digits: Math.max(0, Math.ceil(-Math.log10(step) - 1e-9)) };
}
