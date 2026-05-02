/**
 * Empty-state and loading-state primitives. Every screen that fetches
 * remote data uses these — no mock fixtures, so empty is a real UX.
 */

import { ActivityIndicator, StyleSheet, View } from 'react-native';

import { useTheme } from '../theme/ThemeProvider';
import { Text } from './Text';

export function Loading({ label }: { label?: string }) {
  const theme = useTheme();
  return (
    <View style={styles.box}>
      <ActivityIndicator color={theme.colors.accent2} />
      {label ? (
        <Text variant="caption" tone="tertiary" style={{ marginTop: 8 }}>
          {label}
        </Text>
      ) : null}
    </View>
  );
}

export function Empty({ title, sub }: { title: string; sub?: string }) {
  return (
    <View style={styles.box}>
      <Text variant="heading" tone="secondary">
        {title}
      </Text>
      {sub ? (
        <Text variant="caption" tone="tertiary" style={{ marginTop: 6, textAlign: 'center' }}>
          {sub}
        </Text>
      ) : null}
    </View>
  );
}

export function ErrorState({ title, sub }: { title: string; sub?: string }) {
  return (
    <View style={styles.box}>
      <Text variant="heading" tone="danger">
        {title}
      </Text>
      {sub ? (
        <Text variant="caption" tone="tertiary" style={{ marginTop: 6, textAlign: 'center' }}>
          {sub}
        </Text>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 32,
    paddingHorizontal: 18,
  },
});
