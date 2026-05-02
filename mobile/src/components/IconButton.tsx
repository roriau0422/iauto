/**
 * Pressable circular icon button — `.icon-btn` from styles.css.
 */

import { type ReactNode } from 'react';
import { Pressable, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import { useTheme } from '../theme/ThemeProvider';

type Props = {
  children: ReactNode;
  onPress?: () => void;
  size?: number;
  style?: StyleProp<ViewStyle>;
  filled?: boolean;
  active?: boolean;
};

export function IconButton({ children, onPress, size = 36, style, filled, active }: Props) {
  const theme = useTheme();
  const bg = filled
    ? theme.colors.accent
    : active
      ? theme.colors.accentGlow
      : theme.name === 'dark'
        ? 'rgba(140,175,255,0.06)'
        : 'rgba(20,40,80,0.04)';
  const border = filled ? 'transparent' : theme.colors.stroke2;
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [
        styles.base,
        {
          width: size,
          height: size,
          borderRadius: size / 2,
          backgroundColor: bg,
          borderColor: border,
          opacity: pressed ? 0.7 : 1,
        },
        style,
      ]}
    >
      <View style={styles.inner}>{children}</View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  base: {
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: StyleSheet.hairlineWidth,
  },
  inner: { alignItems: 'center', justifyContent: 'center' },
});
