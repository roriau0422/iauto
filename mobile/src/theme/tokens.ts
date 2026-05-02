/**
 * iAuto design tokens — direct port of project/styles.css.
 *
 * "Immersive blue gradients, glassy" — vibe 0/3 from the design chat.
 * Dark-first; light theme is a light-mode rework of the same accents.
 *
 * Three switches drive the visual style at runtime:
 *   - accent: blue | teal | violet
 *   - radius: sharp | soft | pill
 *   - card:   flat | elevated | glass
 *
 * Per the design's `--accent` cascade, the accent values are resolved
 * once into `theme.colors.accent*` so RN consumers don't have to walk
 * a CSS variable chain.
 */

export type AccentKey = 'blue' | 'teal' | 'violet';
export type RadiusKey = 'sharp' | 'soft' | 'pill';
export type CardKey = 'flat' | 'elevated' | 'glass';
export type ThemeName = 'dark' | 'light';

export const ACCENT_PRESETS: Record<
  AccentKey,
  { dark: string; light: string; dark2: string; light2: string; glow: string; lglow: string }
> = {
  blue: {
    dark: '#4F8DFF',
    light: '#2563EB',
    dark2: '#7BA8FF',
    light2: '#3B82F6',
    glow: 'rgba(79,141,255,0.55)',
    lglow: 'rgba(37,99,235,0.35)',
  },
  teal: {
    dark: '#3DD9C2',
    light: '#0F766E',
    dark2: '#7BF0DD',
    light2: '#14B8A6',
    glow: 'rgba(61,217,194,0.5)',
    lglow: 'rgba(15,118,110,0.3)',
  },
  violet: {
    dark: '#A89BFF',
    light: '#6D28D9',
    dark2: '#C4B9FF',
    light2: '#8B5CF6',
    glow: 'rgba(168,155,255,0.5)',
    lglow: 'rgba(109,40,217,0.3)',
  },
};

export const RADIUS_PRESETS: Record<RadiusKey, { sm: number; md: number; lg: number; xl: number }> = {
  sharp: { sm: 4, md: 6, lg: 8, xl: 10 },
  soft: { sm: 10, md: 16, lg: 22, xl: 28 },
  pill: { sm: 14, md: 22, lg: 28, xl: 36 },
};

const dark = {
  bg0: '#050816',
  bg1: '#0A1024',
  bg2: '#0E1530',
  surface: 'rgba(20, 30, 60, 0.55)',
  surface2: 'rgba(30, 45, 85, 0.42)',
  stroke: 'rgba(140, 175, 255, 0.14)',
  stroke2: 'rgba(140, 175, 255, 0.08)',
  text: '#EAF0FF',
  text2: 'rgba(234, 240, 255, 0.72)',
  text3: 'rgba(234, 240, 255, 0.46)',
};

const light = {
  bg0: '#F4F6FB',
  bg1: '#FFFFFF',
  bg2: '#EEF2FA',
  surface: 'rgba(255, 255, 255, 0.72)',
  surface2: 'rgba(255, 255, 255, 0.55)',
  stroke: 'rgba(20, 40, 80, 0.10)',
  stroke2: 'rgba(20, 40, 80, 0.06)',
  text: '#0A1024',
  text2: 'rgba(10, 16, 36, 0.66)',
  text3: 'rgba(10, 16, 36, 0.42)',
};

export type Theme = {
  name: ThemeName;
  colors: typeof dark & {
    accent: string;
    accent2: string;
    accentGlow: string;
    success: string;
    warn: string;
    danger: string;
  };
  radius: { sm: number; md: number; lg: number; xl: number };
  cardStyle: CardKey;
  spacing: { xs: number; sm: number; md: number; lg: number; xl: number };
  fonts: { display: string; body: string; mono: string };
};

export function buildTheme(opts: {
  themeName: ThemeName;
  accent: AccentKey;
  radius: RadiusKey;
  card: CardKey;
}): Theme {
  const palette = opts.themeName === 'dark' ? dark : light;
  const a = ACCENT_PRESETS[opts.accent];
  return {
    name: opts.themeName,
    colors: {
      ...palette,
      accent: opts.themeName === 'dark' ? a.dark : a.light,
      accent2: opts.themeName === 'dark' ? a.dark2 : a.light2,
      accentGlow: opts.themeName === 'dark' ? a.glow : a.lglow,
      success: '#7BFFB1',
      warn: '#FFB47B',
      danger: '#FF7B9C',
    },
    radius: RADIUS_PRESETS[opts.radius],
    cardStyle: opts.card,
    spacing: { xs: 4, sm: 8, md: 12, lg: 18, xl: 24 },
    fonts: {
      display: 'Geist-Bold',
      body: 'Geist-Regular',
      mono: 'GeistMono-Regular',
    },
  };
}

/** Background gradient stops for the immersive blue look. */
export function backgroundGradient(themeName: ThemeName): string[] {
  if (themeName === 'dark') {
    return ['#050816', '#0A1024', '#050816'];
  }
  return ['#F4F6FB', '#FFFFFF', '#F4F6FB'];
}

/** Accent overlay applied above the page gradient (radial-style fade). */
export function accentOverlay(themeName: ThemeName, accent: AccentKey): string[] {
  const a = ACCENT_PRESETS[accent];
  return themeName === 'dark'
    ? [a.glow.replace('0.55', '0.25'), 'transparent']
    : [a.lglow.replace('0.35', '0.13'), 'transparent'];
}
