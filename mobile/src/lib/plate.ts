/**
 * Mongolian-plate string utilities.
 *
 * Backend regex per ARCH §3.7 is `^\d{4}[set of MN-uppercase letters]{3}$`,
 * stored without spaces (e.g. "9987УБӨ"). We accept any user-spaced
 * input and normalize before validating + sending.
 */

const MN_UPPER = 'АБВГДЕЁЖЗИЙКЛМНОӨПРСТУҮФХЦЧШЩЪЫЬЭЮЯ';

export const PLATE_REGEX = new RegExp(`^\\d{4}[${MN_UPPER}]{3}$`);

export function normalizePlate(raw: string): string {
  return raw.replace(/\s+/g, '').toUpperCase();
}

export function isValidPlate(raw: string): boolean {
  return PLATE_REGEX.test(normalizePlate(raw));
}

/** Format a plate for display: `9987 УБӨ` (with one breathing space). */
export function formatPlate(raw: string): string {
  const n = normalizePlate(raw);
  if (!isValidPlate(n)) return n;
  return `${n.slice(0, 4)} ${n.slice(4)}`;
}
