/**
 * Onboarding step 3 — phone entry. Hits POST /v1/auth/otp/request.
 *
 * Mongolian numbers can be 8-digit (`88110921`) or e.164 (`+976...`).
 * Backend's `OtpRequestIn` accepts either; we don't reformat here.
 */

import { Feather } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, StyleSheet, TextInput, View } from 'react-native';
import { isAxiosError } from 'axios';

import { requestOtp } from '../../src/auth/api';
import { Button } from '../../src/components/Button';
import { Glass } from '../../src/components/Glass';
import { IconButton } from '../../src/components/IconButton';
import { Screen } from '../../src/components/Screen';
import { Text } from '../../src/components/Text';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function OtpEntry() {
  const router = useRouter();
  const theme = useTheme();
  const [phone, setPhone] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async () => {
    setError(null);
    if (!phone) {
      setError('Утасны дугаараа оруулна уу');
      return;
    }
    setSubmitting(true);
    try {
      const out = await requestOtp({ phone });
      router.push({
        pathname: '/onboarding/verify',
        params: {
          phone,
          cooldown: String(out.cooldown_seconds),
          // Dev-only: backend echoes the OTP code in `debug_code` when
          // SMS is stubbed. We pass it through so the verify screen can
          // pre-fill when present (visible only on dev builds).
          ...(out.debug_code ? { debug_code: out.debug_code } : null),
        },
      });
    } catch (e) {
      const detail = isAxiosError(e)
        ? (e.response?.data as { detail?: string } | undefined)?.detail ?? 'Алдаа гарлаа'
        : 'Алдаа гарлаа';
      setError(detail);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Screen scroll contentStyle={{ paddingHorizontal: 24 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 28 }}>
        <IconButton onPress={() => router.back()}>
          <Feather name="arrow-left" size={18} color={theme.colors.text} />
        </IconButton>
      </View>
      <Text variant="eyebrow" tone="tertiary">
        Алхам 2 / 4
      </Text>
      <Text variant="display" style={{ fontSize: 24, lineHeight: 28, marginTop: 6 }}>
        Утасны дугаараа{'\n'}оруулна уу
      </Text>
      <Text variant="caption" tone="tertiary" style={{ marginTop: 6 }}>
        Бид 4 оронтой код илгээх болно
      </Text>

      <Glass radius="lg" style={{ marginTop: 24, paddingVertical: 6 }}>
        <View style={styles.row}>
          <Text variant="num" tone="tertiary" style={{ fontSize: 16 }}>
            +976
          </Text>
          <TextInput
            value={phone}
            onChangeText={setPhone}
            keyboardType="phone-pad"
            placeholder="9911 2387"
            placeholderTextColor={theme.colors.text3}
            maxLength={16}
            style={[styles.input, { color: theme.colors.text }]}
          />
        </View>
      </Glass>

      {error ? (
        <Text variant="caption" tone="danger" style={{ marginTop: 12 }}>
          {error}
        </Text>
      ) : null}

      <Button
        size="lg"
        label="Код илгээх"
        onPress={onSubmit}
        disabled={submitting}
        rightIcon={submitting ? <ActivityIndicator color="#fff" /> : undefined}
        style={{ marginTop: 28 }}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 14, paddingVertical: 8 },
  input: {
    flex: 1,
    fontSize: 20,
    letterSpacing: 1.5,
    paddingVertical: 6,
    fontWeight: '600',
  },
});
