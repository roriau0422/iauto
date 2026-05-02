/**
 * Tiny SVG line+fill sparkline. The valuation hero + warehouse sales
 * card both use this with different geometries.
 */

import { type ColorValue } from 'react-native';
import Svg, { Defs, LinearGradient, Path, Polyline, Stop } from 'react-native-svg';

import { useTheme } from '../theme/ThemeProvider';

type Props = {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  fill?: boolean;
};

export function Sparkline({ values, width = 280, height = 60, color, fill = true }: Props) {
  const theme = useTheme();
  const c = (color ?? theme.colors.accent2) as ColorValue;
  const n = values.length;
  if (n < 2) {
    return <Svg width={width} height={height} />;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  const xStep = width / (n - 1);
  const points = values
    .map((v, i) => {
      const x = i * xStep;
      const y = height - 4 - ((v - min) / range) * (height - 8);
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');

  const linePath = values
    .map((v, i) => {
      const x = i * xStep;
      const y = height - 4 - ((v - min) / range) * (height - 8);
      return `${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');
  const fillPath = `${linePath} L${(width - 0).toFixed(2)},${height} L0,${height} Z`;

  return (
    <Svg width={width} height={height}>
      <Defs>
        <LinearGradient id="spark-fill" x1="0" y1="0" x2="0" y2="1">
          <Stop offset="0%" stopColor={c} stopOpacity={0.32} />
          <Stop offset="100%" stopColor={c} stopOpacity={0} />
        </LinearGradient>
      </Defs>
      {fill ? <Path d={fillPath} fill="url(#spark-fill)" /> : null}
      <Polyline points={points} stroke={c} strokeWidth={1.6} fill="none" />
    </Svg>
  );
}
