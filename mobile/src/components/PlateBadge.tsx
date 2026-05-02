/**
 * Mongolian license-plate visual — white face, `MGL ★` blue tag on the
 * left, monospace 4 + 3 character split. Used on the onboarding `plate`
 * step and as a smaller chip elsewhere.
 */

import { StyleSheet, View } from 'react-native';

import { Text } from './Text';

type Props = {
  plate: string;
  size?: 'sm' | 'lg';
};

export function PlateBadge({ plate, size = 'lg' }: Props) {
  const big = size === 'lg';
  const num = plate.slice(0, 4);
  const letters = plate.slice(4);

  return (
    <View
      style={[
        styles.box,
        {
          paddingHorizontal: big ? 20 : 12,
          paddingVertical: big ? 14 : 8,
          borderWidth: big ? 4 : 2,
        },
      ]}
    >
      <View
        style={[
          styles.tag,
          {
            width: big ? 28 : 22,
            height: big ? 38 : 28,
          },
        ]}
      >
        <Text style={[styles.star, { fontSize: big ? 8 : 7 }]}>★</Text>
        <Text style={[styles.mgl, { fontSize: big ? 11 : 9 }]}>MGL</Text>
      </View>
      <Text style={[styles.plateText, { fontSize: big ? 30 : 18 }]}>
        {num}
        {' '}
        {letters}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  box: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#FFFFFF',
    borderColor: '#0A1024',
    borderRadius: 8,
    gap: 10,
    alignSelf: 'center',
  },
  tag: {
    backgroundColor: '#0A4DD9',
    borderRadius: 3,
    alignItems: 'center',
    justifyContent: 'center',
  },
  star: { color: '#FFE15B', fontWeight: '800' },
  mgl: { color: '#FFE15B', fontWeight: '800', letterSpacing: 1 },
  plateText: {
    color: '#0A1024',
    fontFamily: 'Courier',
    fontWeight: '800',
    letterSpacing: 1.5,
  },
});
