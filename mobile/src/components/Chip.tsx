/**
 * Chip — pill label. Maps to `.chip` and `.chip-blue` from styles.css.
 */

import { StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import { useTheme } from '../theme/ThemeProvider';
import { Text } from './Text';

type Props = {
  label: string;
  tone?: 'neutral' | 'accent' | 'success' | 'warn' | 'danger';
  style?: StyleProp<ViewStyle>;
};

export function Chip({ label, tone = 'neutral', style }: Props) {
  const theme = useTheme();

  const palette = (() => {
    switch (tone) {
      case 'accent':
        return {
          bg:
            theme.name === 'dark'
              ? 'rgba(79,141,255,0.18)'
              : 'rgba(37,99,235,0.10)',
          text: theme.colors.accent2,
          border: theme.colors.accentGlow,
        };
      case 'success':
        return { bg: 'rgba(123,255,177,0.16)', text: '#7BFFB1', border: 'rgba(123,255,177,0.25)' };
      case 'warn':
        return { bg: 'rgba(255,180,123,0.16)', text: '#FFB47B', border: 'rgba(255,180,123,0.25)' };
      case 'danger':
        return { bg: 'rgba(255,123,156,0.16)', text: '#FF7B9C', border: 'rgba(255,123,156,0.25)' };
      default:
        return {
          bg:
            theme.name === 'dark'
              ? 'rgba(140,175,255,0.10)'
              : 'rgba(20,40,80,0.05)',
          text: theme.colors.text2,
          border: theme.colors.stroke2,
        };
    }
  })();

  return (
    <View
      style={[
        styles.base,
        {
          backgroundColor: palette.bg,
          borderColor: palette.border,
        },
        style,
      ]}
    >
      <Text variant="caption" weight="500" style={{ color: palette.text }}>
        {label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  base: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: 10,
    paddingVertical: 5,
    borderRadius: 9999,
    borderWidth: StyleSheet.hairlineWidth,
    alignSelf: 'flex-start',
  },
});
