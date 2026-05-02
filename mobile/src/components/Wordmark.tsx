/**
 * Brand wordmark — `i` in accent + `Auto` in text. From shared.jsx.
 */

import { StyleSheet, View } from 'react-native';

import { useTheme } from '../theme/ThemeProvider';
import { Text } from './Text';

export function Wordmark({ size = 22 }: { size?: number }) {
  const theme = useTheme();
  return (
    <View style={styles.row}>
      <Text style={[styles.letter, { fontSize: size, color: theme.colors.accent2 }]}>i</Text>
      <Text style={[styles.letter, { fontSize: size, color: theme.colors.text }]}>Auto</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'baseline', gap: 0 },
  letter: { fontWeight: '800', letterSpacing: -1.1, lineHeight: undefined },
});
