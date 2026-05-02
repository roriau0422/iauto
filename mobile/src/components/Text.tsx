/**
 * Typed Text components mapping to the design's typographic scale.
 *
 * Variants:
 *   - display: 26px Geist 800 — onboarding step titles
 *   - title: 19px 700 — screen header
 *   - heading: 16px 700 — section headings
 *   - body: 14px 500
 *   - caption: 12px 500
 *   - eyebrow: 10px 600 uppercase 0.14em letterspacing
 *   - mono: Geist Mono — numeric data, plates, VIN
 *   - num: Geist Mono 500 -0.04em letterspacing — hero numbers
 */

import { Text as RNText, StyleSheet, type TextProps, type TextStyle } from 'react-native';

import { useTheme } from '../theme/ThemeProvider';

type Variant =
  | 'display'
  | 'title'
  | 'heading'
  | 'body'
  | 'caption'
  | 'eyebrow'
  | 'mono'
  | 'num';

type Tone = 'primary' | 'secondary' | 'tertiary' | 'accent' | 'inverse' | 'success' | 'warn' | 'danger';

type Props = TextProps & {
  variant?: Variant;
  tone?: Tone;
  weight?: '400' | '500' | '600' | '700' | '800';
};

export function Text({ variant = 'body', tone = 'primary', weight, style, children, ...rest }: Props) {
  const theme = useTheme();
  const variantStyle = VARIANTS[variant];
  const toneColor =
    tone === 'primary'
      ? theme.colors.text
      : tone === 'secondary'
        ? theme.colors.text2
        : tone === 'tertiary'
          ? theme.colors.text3
          : tone === 'accent'
            ? theme.colors.accent
            : tone === 'inverse'
              ? theme.name === 'dark'
                ? '#0A1024'
                : '#FFFFFF'
              : tone === 'success'
                ? theme.colors.success
                : tone === 'warn'
                  ? theme.colors.warn
                  : theme.colors.danger;

  return (
    <RNText
      {...rest}
      style={[variantStyle, { color: toneColor }, weight ? { fontWeight: weight } : null, style]}
    >
      {children}
    </RNText>
  );
}

const VARIANTS: Record<Variant, TextStyle> = StyleSheet.create({
  display: { fontSize: 26, fontWeight: '800', letterSpacing: -0.9, lineHeight: 32 },
  title: { fontSize: 19, fontWeight: '700', letterSpacing: -0.4, lineHeight: 24 },
  heading: { fontSize: 16, fontWeight: '700', letterSpacing: -0.2, lineHeight: 22 },
  body: { fontSize: 14, fontWeight: '500', lineHeight: 20 },
  caption: { fontSize: 12, fontWeight: '500', lineHeight: 16 },
  eyebrow: {
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 1.4,
    textTransform: 'uppercase',
    lineHeight: 14,
  },
  mono: {
    fontSize: 13,
    fontFamily: 'Courier',
    fontVariant: ['tabular-nums'],
  },
  num: {
    fontFamily: 'Courier',
    fontVariant: ['tabular-nums'],
    fontWeight: '500',
    letterSpacing: -0.8,
  },
}) as Record<Variant, TextStyle>;
