/**
 * Reusable screen header — eyebrow + title + left/right slot.
 *
 * Mirrors the design's `ScreenHeader` shared primitive. Stays inside the
 * standard 18px horizontal padding the screens use.
 */

import { type ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { Text } from './Text';

type Props = {
  title: string;
  sub?: string;
  left?: ReactNode;
  right?: ReactNode;
};

export function ScreenHeader({ title, sub, left, right }: Props) {
  return (
    <View style={styles.row}>
      {left}
      <View style={styles.center}>
        {sub ? <Text variant="eyebrow">{sub}</Text> : null}
        <Text variant="title" numberOfLines={1}>
          {title}
        </Text>
      </View>
      {right ? <View style={styles.right}>{right}</View> : null}
    </View>
  );
}

const styles = StyleSheet.create({
  row: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 12,
    paddingHorizontal: 18,
    paddingTop: 14,
    paddingBottom: 10,
  },
  center: { flex: 1, minWidth: 0 },
  right: { flexDirection: 'row', alignItems: 'center', gap: 6 },
});
