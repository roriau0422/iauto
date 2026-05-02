/**
 * Onboarding step 4 — plate entry + XYP lookup.
 *
 * Validates `^\d{4}[MN-uppercase]{3}$` client-side, then runs the XYP
 * lookup via the device-side runner. Outcomes:
 *   - registered  → push /reveal with the new vehicle id
 *   - not_found   → friendly empty state in-place ("дугаараар олдсонгүй")
 *   - gateway_err → friendly error banner; backend has paged the operator
 */

import { Feather } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { ActivityIndicator, Pressable, StyleSheet, TextInput, View } from 'react-native';

import { Button } from '../../src/components/Button';
import { Glass } from '../../src/components/Glass';
import { IconButton } from '../../src/components/IconButton';
import { PlateBadge } from '../../src/components/PlateBadge';
import { Screen } from '../../src/components/Screen';
import { Text } from '../../src/components/Text';
import { useTheme } from '../../src/theme/ThemeProvider';
import { isValidPlate, normalizePlate } from '../../src/lib/plate';
import { runXypLookup } from '../../src/lib/xypLookup';

export default function PlateScreen() {
  const theme = useTheme();
  const router = useRouter();
  const [plate, setPlate] = useState('');
  const [phase, setPhase] = useState<'idle' | 'looking' | 'not_found' | 'error'>('idle');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const onLookup = async () => {
    const norm = normalizePlate(plate);
    if (!isValidPlate(norm)) {
      setErrorMsg('4 тоо + 3 кирилл том үсэг — жишээ нь 9987УБӨ');
      return;
    }
    setErrorMsg(null);
    setPhase('looking');
    const outcome = await runXypLookup(norm);
    if (outcome.kind === 'registered') {
      router.replace({
        pathname: '/onboarding/reveal',
        params: { vehicle_id: outcome.result.vehicle.id },
      });
      return;
    }
    if (outcome.kind === 'not_found') {
      setPhase('not_found');
      return;
    }
    setPhase('error');
    setErrorMsg(`XYP алдаа · ${outcome.statusCode}`);
  };

  const trimmed = normalizePlate(plate);
  const valid = isValidPlate(trimmed);
  const previewPlate = valid ? trimmed : trimmed.padEnd(7, '–');

  return (
    <Screen scroll contentStyle={{ paddingHorizontal: 24 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', gap: 8, marginBottom: 28 }}>
        <IconButton onPress={() => router.back()}>
          <Feather name="arrow-left" size={18} color={theme.colors.text} />
        </IconButton>
      </View>
      <Text variant="eyebrow" tone="tertiary">
        Алхам 3 / 4
      </Text>
      <Text variant="display" style={{ fontSize: 24, lineHeight: 28, marginTop: 6 }}>
        Машины{'\n'}дугаараа оруулна уу
      </Text>
      <Text variant="caption" tone="tertiary" style={{ marginTop: 6 }}>
        Бид ХЗГ-ын мэдээллийн санд тулгах болно
      </Text>

      <View style={{ marginTop: 36, alignItems: 'center' }}>
        <Pressable onPress={() => null}>
          <PlateBadge plate={previewPlate} />
        </Pressable>
      </View>

      <Glass radius="md" style={{ marginTop: 16 }}>
        <View style={styles.row}>
          <Feather name="edit-3" size={16} color={theme.colors.text2} />
          <TextInput
            value={plate}
            onChangeText={(v) => setPlate(v.toUpperCase())}
            autoCapitalize="characters"
            autoCorrect={false}
            placeholder="9987УБӨ"
            placeholderTextColor={theme.colors.text3}
            maxLength={7}
            style={[styles.input, { color: theme.colors.text }]}
          />
        </View>
      </Glass>

      <Text variant="mono" tone="tertiary" style={{ marginTop: 12, textAlign: 'center', fontSize: 11, letterSpacing: 1.2 }}>
        XYP · SMARTCAR.MN
      </Text>

      {errorMsg ? (
        <Text variant="caption" tone="danger" style={{ marginTop: 12 }}>
          {errorMsg}
        </Text>
      ) : null}

      {phase === 'not_found' ? (
        <Glass radius="md" style={{ marginTop: 12, borderColor: theme.colors.warn, borderWidth: 0.5 }}>
          <Text variant="heading" tone="warn">
            Дугаараар олдсонгүй
          </Text>
          <Text variant="caption" tone="secondary" style={{ marginTop: 6, lineHeight: 18 }}>
            ХЗГ-ын мэдээллийн санд тохирох машин олдсонгүй. Үсэг тоог дахин шалгана уу — кирилл
            үсгийг латин 'O' эсвэл 'A' гэж андуурахгүй байх нь чухал.
          </Text>
        </Glass>
      ) : null}

      <Button
        size="lg"
        label={phase === 'looking' ? 'XYP-аас шалгаж байна…' : 'Дугаар хайх'}
        onPress={onLookup}
        disabled={phase === 'looking' || !valid}
        loading={phase === 'looking'}
        leftIcon={phase === 'looking' ? <ActivityIndicator color="#fff" /> : <Feather name="search" size={18} color="#fff" />}
        style={{ marginTop: 28 }}
      />

      <Text variant="caption" tone="tertiary" style={{ textAlign: 'center', marginTop: 14 }}>
        Эсвэл дараа нэмж болно
      </Text>
    </Screen>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', alignItems: 'center', gap: 12 },
  input: {
    flex: 1,
    fontSize: 18,
    letterSpacing: 1.6,
    paddingVertical: 8,
    fontWeight: '600',
  },
});
