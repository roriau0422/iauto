/**
 * Onboarding step 3b — 4-digit OTP entry. Hits POST /v1/auth/otp/verify.
 *
 * On success we set the session in `useAuth`, then push to /plate so
 * the user can register their first car. The auth-aware redirect in
 * the root layout will eventually take over and route to the role's
 * tab tree once we exit the onboarding stack.
 */

import { Feather } from '@expo/vector-icons';
import { useLocalSearchParams, useRouter } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import {
  Keyboard,
  Platform,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';
import { isAxiosError } from 'axios';

import { verifyOtp } from '../../src/auth/api';
import { useAuth, type Role } from '../../src/auth/store';
import { Button } from '../../src/components/Button';
import { Glass } from '../../src/components/Glass';
import { IconButton } from '../../src/components/IconButton';
import { Screen } from '../../src/components/Screen';
import { Text } from '../../src/components/Text';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function OtpVerify() {
  const theme = useTheme();
  const router = useRouter();
  const params = useLocalSearchParams<{ phone?: string; debug_code?: string; cooldown?: string }>();
  const setSession = useAuth((s) => s.setSession);
  const role = useAuth((s) => s.role);

  const [code, setCode] = useState(params.debug_code ?? '');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<TextInput>(null);

  useEffect(() => {
    // Auto-focus the hidden input so the keypad pops up immediately.
    const t = setTimeout(() => inputRef.current?.focus(), 250);
    return () => clearTimeout(t);
  }, []);

  // Auto-submit when 4 digits arrive.
  useEffect(() => {
    if (code.length === 4 && !submitting) {
      void onVerify();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [code]);

  const onVerify = async () => {
    if (code.length !== 4 || !params.phone) return;
    setSubmitting(true);
    setError(null);
    try {
      const tokens = await verifyOtp({
        phone: params.phone,
        code,
        role: (role ?? 'driver') as Role,
      });
      await setSession(
        { access_token: tokens.access_token, refresh_token: tokens.refresh_token },
        tokens.user,
      );
      Keyboard.dismiss();
      // Drivers proceed to the plate registration step. Businesses
      // skip ahead to their dashboard — they don't need a personal car.
      if (tokens.user.role === 'business') {
        router.replace('/(business)');
      } else {
        router.push('/onboarding/plate');
      }
    } catch (e) {
      setSubmitting(false);
      const detail = isAxiosError(e)
        ? (e.response?.data as { detail?: string } | undefined)?.detail ??
          'Код буруу эсвэл хугацаа дууссан'
        : 'Алдаа гарлаа';
      setError(detail);
      setCode('');
      inputRef.current?.focus();
    }
  };

  const cells = [0, 1, 2, 3].map((i) => code[i] ?? '');

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
        Баталгаажуулах{'\n'}код илгээгдлээ
      </Text>
      <Text variant="caption" tone="tertiary" style={{ marginTop: 6 }}>
        +976 {params.phone ? formatTail(params.phone) : ''} руу 4 оронтой код илгээсэн
      </Text>

      <View style={{ flexDirection: 'row', gap: 10, marginTop: 28 }} onTouchEnd={() => inputRef.current?.focus()}>
        {cells.map((c, i) => {
          const isActive = i === code.length;
          return (
            <Glass
              key={i}
              radius="md"
              style={[
                styles.cell,
                isActive
                  ? { borderColor: theme.colors.accent, borderWidth: 1 }
                  : null,
              ]}
            >
              <Text variant="num" weight="700" style={{ fontSize: 24 }}>
                {c}
              </Text>
            </Glass>
          );
        })}
      </View>

      <TextInput
        ref={inputRef}
        value={code}
        onChangeText={(v) => setCode(v.replace(/\D/g, '').slice(0, 4))}
        keyboardType="number-pad"
        textContentType={Platform.OS === 'ios' ? 'oneTimeCode' : 'none'}
        autoComplete="one-time-code"
        style={styles.hiddenInput}
        editable={!submitting}
      />

      {params.debug_code ? (
        <Text variant="caption" tone="warn" style={{ marginTop: 12 }}>
          DEV: код {params.debug_code}
        </Text>
      ) : null}

      {error ? (
        <Text variant="caption" tone="danger" style={{ marginTop: 12 }}>
          {error}
        </Text>
      ) : null}

      <Button
        size="lg"
        label={submitting ? 'Шалгаж байна…' : 'Үргэлжлүүлэх'}
        onPress={onVerify}
        disabled={submitting || code.length !== 4}
        loading={submitting}
        style={{ marginTop: 28 }}
      />
    </Screen>
  );
}

function formatTail(p: string): string {
  // Just present last 8 digits as 4-4 — quick visual without Intl libs.
  const digits = p.replace(/\D/g, '');
  const tail = digits.slice(-8);
  if (tail.length === 8) return `${tail.slice(0, 4)}-${tail.slice(4)}`;
  return p;
}

const styles = StyleSheet.create({
  cell: {
    flex: 1,
    minHeight: 60,
    alignItems: 'center',
    justifyContent: 'center',
  },
  hiddenInput: {
    position: 'absolute',
    opacity: 0,
    height: 1,
    width: 1,
  },
});
