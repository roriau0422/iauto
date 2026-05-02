/**
 * Onboarding step 2 — soft welcome before OTP.
 */

import { Feather } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { StyleSheet, View } from 'react-native';

import { Button } from '../../src/components/Button';
import { Screen } from '../../src/components/Screen';
import { Text } from '../../src/components/Text';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function Welcome() {
  const router = useRouter();
  const theme = useTheme();
  return (
    <Screen scroll={false} contentStyle={{ flex: 1, paddingHorizontal: 24, paddingBottom: 24 }}>
      <View style={styles.center}>
        <View style={[styles.iAvatar, { backgroundColor: theme.colors.accent }]}>
          <Text style={styles.iLetter}>i</Text>
        </View>
        <Text variant="display" style={{ fontSize: 32, lineHeight: 36, textAlign: 'center', marginTop: 18 }}>
          Машинаа{'\n'}амьдруул
        </Text>
        <Text variant="body" tone="tertiary" style={{ textAlign: 'center', marginTop: 12, maxWidth: 280, lineHeight: 20 }}>
          Дугаараараа бүртгүүл, эд ангиа ол, AI механиктай ярилц, машиныхаа үнэ цэнийг мэдэж
          ав.
        </Text>
      </View>
      <Button
        label="Утасны дугаараар үргэлжлүүлэх"
        size="lg"
        onPress={() => router.push('/onboarding/otp')}
        rightIcon={<Feather name="arrow-right" size={18} color="#fff" />}
      />
      <Text variant="caption" tone="tertiary" style={{ textAlign: 'center', marginTop: 6 }}>
        Үргэлжлүүлснээр Үйлчилгээний нөхцөл-ийг зөвшөөрнө
      </Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  iAvatar: {
    width: 88,
    height: 88,
    borderRadius: 26,
    alignItems: 'center',
    justifyContent: 'center',
  },
  iLetter: {
    color: '#fff',
    fontSize: 48,
    fontWeight: '800',
    letterSpacing: -2.4,
  },
});
