/**
 * Tiny formatters — Mongolian Tugrik, integer-only "x.y M" abbreviation,
 * relative-time, etc. Kept dependency-free so we don't pull in moment /
 * date-fns until we actually need locale-aware formatting.
 */

/** "1,284" — thousands separators, no decimals. */
export function fmt(n: number): string {
  return n.toLocaleString('en-US');
}

/** "1,284₮" */
export function mnt(n: number): string {
  return `${fmt(n)}₮`;
}

/** "40.8M₮" — millions, one decimal. */
export function mntMillions(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M₮`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}k₮`;
  return mnt(n);
}

/** "2 хоног", "5 цаг", "23 мин", "дөнгөж сая" */
export function relativeMn(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    const ts = new Date(iso).getTime();
    if (Number.isNaN(ts)) return '—';
    const diffMs = Date.now() - ts;
    const min = Math.round(diffMs / 60_000);
    if (min < 1) return 'дөнгөж сая';
    if (min < 60) return `${min} мин`;
    const hr = Math.round(min / 60);
    if (hr < 24) return `${hr} ц`;
    const day = Math.round(hr / 24);
    if (day < 30) return `${day} хоног`;
    const mon = Math.round(day / 30);
    if (mon < 12) return `${mon} сар`;
    const yr = Math.round(mon / 12);
    return `${yr} жил`;
  } catch {
    return '—';
  }
}

/** "2026/05/02" */
export function dateOnly(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    const d = new Date(iso);
    return `${d.getFullYear()}/${String(d.getMonth() + 1).padStart(2, '0')}/${String(d.getDate()).padStart(2, '0')}`;
  } catch {
    return '—';
  }
}

/** "14:23" */
export function timeOnly(iso: string | null | undefined): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  } catch {
    return '';
  }
}

/** Mongolian fuel label for an XYP-side fuel string. */
export function fuelLabelMn(s: string | null | undefined): string {
  if (!s) return '—';
  const t = s.toLowerCase();
  if (t === 'petrol' || t === 'gasoline' || t === 'бензин') return 'Бензин';
  if (t === 'diesel' || t === 'дизель') return 'Дизель';
  if (t === 'hybrid' || t === 'хосолмол') return 'Хосолмол';
  if (t === 'electric' || t === 'цахилгаан') return 'Цахилгаан';
  if (t === 'lpg' || t === 'gas' || t === 'хий') return 'Хий';
  return s;
}
