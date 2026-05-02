/**
 * Glass surface — port of `.glass` + card-style variants from styles.css.
 *
 * Three modes driven by `theme.cardStyle`:
 *   - glass: BlurView with translucent fill + thin stroke
 *   - elevated: opaque fill + heavy shadow
 *   - flat: opaque fill + thin stroke, no shadow
 *
 * BlurView from expo-blur — supported on iOS/Android with the new
 * architecture. On Android the blur is approximate; we layer an
 * opaque fallback fill underneath.
 */

import { BlurView } from 'expo-blur';
import { type ReactNode } from 'react';
import { Platform, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import { useTheme } from '../theme/ThemeProvider';

type Props = {
  children: ReactNode;
  style?: StyleProp<ViewStyle>;
  radius?: 'sm' | 'md' | 'lg' | 'xl';
  /** Override the theme's card style for this surface only (e.g. force flat for nested chips). */
  variant?: 'flat' | 'elevated' | 'glass';
};

export function Glass({ children, style, radius = 'md', variant }: Props) {
  const theme = useTheme();
  const r = theme.radius[radius];
  const mode = variant ?? theme.cardStyle;

  if (mode === 'glass') {
    return (
      <View style={[styles.base, { borderRadius: r, borderColor: theme.colors.stroke, borderWidth: StyleSheet.hairlineWidth }, style]}>
        <BlurView
          tint={theme.name === 'dark' ? 'dark' : 'light'}
          intensity={Platform.OS === 'android' ? 60 : 40}
          style={StyleSheet.absoluteFill}
        />
        <View style={[StyleSheet.absoluteFill, { backgroundColor: theme.colors.surface }]} />
        <View style={{ padding: theme.spacing.md }}>{children}</View>
      </View>
    );
  }

  if (mode === 'elevated') {
    const elevatedFill = theme.name === 'dark' ? 'rgba(18, 28, 60, 0.95)' : '#FFFFFF';
    return (
      <View
        style={[
          styles.base,
          {
            borderRadius: r,
            backgroundColor: elevatedFill,
            shadowColor: theme.name === 'dark' ? '#000814' : '#142850',
            shadowOpacity: theme.name === 'dark' ? 0.6 : 0.1,
            shadowRadius: 20,
            shadowOffset: { width: 0, height: 14 },
            elevation: 6,
          },
          style,
        ]}
      >
        <View style={{ padding: theme.spacing.md }}>{children}</View>
      </View>
    );
  }

  // flat
  const flatFill = theme.name === 'dark' ? 'rgba(14, 21, 48, 0.85)' : '#FFFFFF';
  return (
    <View
      style={[
        styles.base,
        {
          borderRadius: r,
          backgroundColor: flatFill,
          borderColor: theme.colors.stroke,
          borderWidth: StyleSheet.hairlineWidth,
        },
        style,
      ]}
    >
      <View style={{ padding: theme.spacing.md }}>{children}</View>
    </View>
  );
}

const styles = StyleSheet.create({
  base: {
    overflow: 'hidden',
  },
});
