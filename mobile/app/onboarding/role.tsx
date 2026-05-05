/**
 * Onboarding step 1/5 — role pick (driver / business).
 *
 * Saves the selected role to the auth store + SecureStore so it
 * survives both restart and the OTP verify call (`role` is part of
 * `OtpVerifyIn` server-side and is what flips the user's permanent
 * role on registration).
 */

import { Feather, MaterialCommunityIcons } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { Button } from '../../src/components/Button';
import { Chip } from '../../src/components/Chip';
import { Glass } from '../../src/components/Glass';
import { Screen } from '../../src/components/Screen';
import { Text } from '../../src/components/Text';
import { useAuth, type Role } from '../../src/auth/store';
import { useTheme } from '../../src/theme/ThemeProvider';

type Choice = {
  key: Extract<Role, 'driver' | 'business'>;
  title: string;
  sub: string;
  bullets: string[];
  icon: 'car' | 'package';
};

const CHOICES: Choice[] = [
  {
    key: 'driver',
    title: 'Би бол жолооч',
    sub: 'Машинаа удирдах, эд анги авах,\nAI механиктай ярилцах',
    bullets: ['Дугаараараа бүртгэл', 'Зах зээл + чат', 'AI механик + үнэлгээ'],
    icon: 'car',
  },
  {
    key: 'business',
    title: 'Би бизнес эрхлэгч',
    sub: 'Эд анги нийлүүлэх, агуулахаа\nудирдах, бизнесээ өргөжүүл',
    bullets: ['Агуулах + бараа материал', 'Захиалга + борлуулалт', 'Зорилтот зар + статистик'],
    icon: 'package',
  },
];

export default function RolePick() {
  const theme = useTheme();
  const router = useRouter();
  const setRole = useAuth((s) => s.setRole);
  const [picked, setPicked] = useState<Choice['key'] | null>(null);

  const onContinue = async () => {
    if (!picked) return;
    await setRole(picked);
    router.push('/onboarding/welcome');
  };

  return (
    <Screen scroll contentStyle={{ paddingHorizontal: 20, paddingTop: 8 }}>
      <View style={[styles.iAvatar, { backgroundColor: theme.colors.accent }]}>
        <Text variant="display" tone="inverse" style={styles.iLetter}>
          i
        </Text>
      </View>
      <Text variant="eyebrow" tone="tertiary" style={{ marginTop: 18 }}>
        Алхам 1 / 5
      </Text>
      <Text variant="display" style={{ marginTop: 4 }}>
        Хэн бэ?
      </Text>
      <Text variant="caption" tone="tertiary" style={{ marginTop: 6, lineHeight: 18, maxWidth: 280 }}>
        UCar-г жолоочийн эсвэл бизнесийн хэрэглээнд тохируулна. Дараа тохиргооноос солих
        боломжтой.
      </Text>

      <View style={{ gap: 10, marginTop: 22 }}>
        {CHOICES.map((c) => {
          const active = picked === c.key;
          return (
            <Pressable
              key={c.key}
              onPress={() => setPicked(c.key)}
              style={({ pressed }) => ({ opacity: pressed ? 0.9 : 1 })}
            >
              <Glass
                radius="lg"
                style={[
                  active
                    ? {
                        borderColor: theme.colors.accent,
                        borderWidth: 1.5,
                        shadowColor: theme.colors.accent,
                        shadowOpacity: 0.4,
                        shadowRadius: 18,
                      }
                    : null,
                ]}
              >
                <View style={{ flexDirection: 'row', alignItems: 'flex-start', gap: 12 }}>
                  <View
                    style={[
                      styles.iconBox,
                      {
                        backgroundColor: active ? theme.colors.accent : 'rgba(140,175,255,0.06)',
                      },
                    ]}
                  >
                    {c.icon === 'car' ? (
                      <MaterialCommunityIcons name="car" size={22} color={active ? '#fff' : theme.colors.text2} />
                    ) : (
                      <Feather name="package" size={22} color={active ? '#fff' : theme.colors.text2} />
                    )}
                  </View>
                  <View style={{ flex: 1, minWidth: 0 }}>
                    <Text variant="heading">{c.title}</Text>
                    <Text variant="caption" tone="tertiary" style={{ marginTop: 3 }}>
                      {c.sub}
                    </Text>
                  </View>
                  <View
                    style={[
                      styles.radio,
                      active
                        ? { backgroundColor: theme.colors.accent, borderColor: 'transparent' }
                        : { borderColor: theme.colors.stroke },
                    ]}
                  >
                    {active ? <Feather name="check" size={14} color="#fff" /> : null}
                  </View>
                </View>
                <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6, marginTop: 12, paddingLeft: 56 }}>
                  {c.bullets.map((b) => (
                    <Chip key={b} label={b} tone={active ? 'accent' : 'neutral'} />
                  ))}
                </View>
              </Glass>
            </Pressable>
          );
        })}
      </View>

      <View style={{ flex: 1, minHeight: 24 }} />

      <Button
        label="Үргэлжлүүлэх"
        size="lg"
        disabled={!picked}
        onPress={onContinue}
        rightIcon={<Feather name="arrow-right" size={18} color="#fff" />}
        style={{ marginTop: 24 }}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  iAvatar: {
    width: 44,
    height: 44,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  iLetter: { fontSize: 26, lineHeight: 30 },
  iconBox: {
    width: 44,
    height: 44,
    borderRadius: 12,
    alignItems: 'center',
    justifyContent: 'center',
  },
  radio: {
    width: 22,
    height: 22,
    borderRadius: 11,
    borderWidth: 1.5,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
