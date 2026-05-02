/**
 * Button — port of `.btn` `.btn-primary` `.btn-ghost` `.btn-pill`.
 *
 * Primary uses a 135° gradient from accent → deep blue with a glow.
 * Ghost is a hairline-bordered transparent surface.
 */

import * as Haptics from 'expo-haptics';
import { LinearGradient } from 'expo-linear-gradient';
import { type ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';

import { useTheme } from '../theme/ThemeProvider';
import { Text } from './Text';

type Props = {
  label?: string;
  children?: ReactNode;
  onPress?: () => void;
  variant?: 'primary' | 'ghost' | 'danger';
  pill?: boolean;
  loading?: boolean;
  disabled?: boolean;
  size?: 'sm' | 'md' | 'lg';
  haptic?: boolean;
  style?: StyleProp<ViewStyle>;
  leftIcon?: ReactNode;
  rightIcon?: ReactNode;
};

export function Button({
  label,
  children,
  onPress,
  variant = 'primary',
  pill = false,
  loading = false,
  disabled = false,
  size = 'md',
  haptic = true,
  style,
  leftIcon,
  rightIcon,
}: Props) {
  const theme = useTheme();
  const sizeStyles = SIZES[size];
  const radius = pill ? 9999 : theme.radius.sm;

  const handle = () => {
    if (disabled || loading) return;
    if (haptic) Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Light).catch(() => undefined);
    onPress?.();
  };

  const content = (
    <View style={styles.row}>
      {loading ? (
        <ActivityIndicator color="#fff" />
      ) : (
        <>
          {leftIcon}
          {label ? (
            <Text variant="body" weight="600" tone={variant === 'ghost' ? 'primary' : 'inverse'}>
              {label}
            </Text>
          ) : null}
          {children}
          {rightIcon}
        </>
      )}
    </View>
  );

  if (variant === 'primary') {
    return (
      <Pressable
        onPress={handle}
        disabled={disabled || loading}
        style={({ pressed }) => [
          {
            borderRadius: radius,
            opacity: disabled ? 0.5 : pressed ? 0.92 : 1,
            shadowColor: theme.colors.accent,
            shadowOpacity: 0.45,
            shadowRadius: 14,
            shadowOffset: { width: 0, height: 6 },
            elevation: 4,
          },
          style,
        ]}
      >
        <LinearGradient
          colors={[theme.colors.accent, '#2563EB']}
          start={{ x: 0, y: 0 }}
          end={{ x: 1, y: 1 }}
          style={[styles.surface, sizeStyles, { borderRadius: radius }]}
        >
          {content}
        </LinearGradient>
      </Pressable>
    );
  }

  if (variant === 'danger') {
    return (
      <Pressable
        onPress={handle}
        disabled={disabled || loading}
        style={({ pressed }) => [
          styles.surface,
          sizeStyles,
          {
            borderRadius: radius,
            backgroundColor: theme.colors.danger,
            opacity: disabled ? 0.5 : pressed ? 0.9 : 1,
          },
          style,
        ]}
      >
        {content}
      </Pressable>
    );
  }

  // ghost
  return (
    <Pressable
      onPress={handle}
      disabled={disabled || loading}
      style={({ pressed }) => [
        styles.surface,
        sizeStyles,
        {
          borderRadius: radius,
          borderColor: theme.colors.stroke,
          borderWidth: StyleSheet.hairlineWidth,
          backgroundColor: 'transparent',
          opacity: disabled ? 0.5 : pressed ? 0.85 : 1,
        },
        style,
      ]}
    >
      {content}
    </Pressable>
  );
}

const SIZES = {
  sm: { paddingHorizontal: 12, paddingVertical: 8, minHeight: 34 },
  md: { paddingHorizontal: 16, paddingVertical: 12, minHeight: 44 },
  lg: { paddingHorizontal: 20, paddingVertical: 14, minHeight: 52 },
};

const styles = StyleSheet.create({
  surface: { alignItems: 'center', justifyContent: 'center' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 8 },
});
