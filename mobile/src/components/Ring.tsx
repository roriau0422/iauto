/**
 * Circular progress ring with label/sub centerpiece. Used by the
 * dashboard "AI оношилгоо" card and the service-due ring.
 */

import { View } from 'react-native';
import Svg, { Circle } from 'react-native-svg';

import { useTheme } from '../theme/ThemeProvider';
import { Text } from './Text';

type Props = {
  size?: number;
  value: number;
  label?: string;
  sub?: string;
  stroke?: number;
};

export function Ring({ size = 64, value, label, sub, stroke = 4 }: Props) {
  const theme = useTheme();
  const r = (size - stroke * 2) / 2;
  const c = 2 * Math.PI * r;
  const filled = Math.max(0, Math.min(1, value));

  return (
    <View style={{ width: size, height: size }}>
      <Svg width={size} height={size} style={{ transform: [{ rotate: '-90deg' }] }}>
        <Circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={theme.colors.stroke}
          strokeWidth={stroke}
        />
        <Circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={theme.colors.accent2}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${c * filled} ${c}`}
        />
      </Svg>
      <View
        style={{
          position: 'absolute',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {label ? (
          <Text variant="num" weight="700" style={{ fontSize: 14 }}>
            {label}
          </Text>
        ) : null}
        {sub ? (
          <Text variant="eyebrow" tone="tertiary">
            {sub}
          </Text>
        ) : null}
      </View>
    </View>
  );
}
