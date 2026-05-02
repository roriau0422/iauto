/**
 * Settings — theme/accent/radius/card tweaks + logout.
 *
 * Mirrors the design's `tweaks-panel.jsx`. The toggles call into
 * `useTweaks().setTweak(k, v)` which persists to SecureStore.
 */

import { Feather } from '@expo/vector-icons';
import { useRouter } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import { useAuth } from '../../src/auth/store';
import { Button } from '../../src/components/Button';
import { Chip } from '../../src/components/Chip';
import { Glass } from '../../src/components/Glass';
import { IconButton } from '../../src/components/IconButton';
import { Screen } from '../../src/components/Screen';
import { ScreenHeader } from '../../src/components/ScreenHeader';
import { Text } from '../../src/components/Text';
import { useTheme, useTweaks } from '../../src/theme/ThemeProvider';
import type {
  AccentKey,
  CardKey,
  RadiusKey,
  ThemeName,
} from '../../src/theme/tokens';

export default function SettingsScreen() {
  const router = useRouter();
  const theme = useTheme();
  const { tweaks, setTweak } = useTweaks();
  const user = useAuth((s) => s.user);
  const logout = useAuth((s) => s.logout);

  return (
    <Screen scroll>
      <ScreenHeader
        sub="ТОХИРГОО"
        title="Хэв маяг"
        left={
          <IconButton onPress={() => router.back()}>
            <Feather name="arrow-left" size={18} color={theme.colors.text} />
          </IconButton>
        }
      />

      <View style={{ paddingHorizontal: 18 }}>
        {user ? (
          <Glass radius="md">
            <Text variant="eyebrow" tone="tertiary">
              ХЭРЭГЛЭГЧ
            </Text>
            <Text variant="body" weight="600" style={{ marginTop: 4 }}>
              {user.display_name ?? user.phone}
            </Text>
            <Text variant="caption" tone="tertiary">
              Үүрэг — {user.role}
            </Text>
          </Glass>
        ) : null}

        <Section title="Дэлгэцийн горим">
          <Row>
            {(['system', 'dark', 'light'] as const).map((t) => (
              <Pressable key={t} onPress={() => setTweak('theme', t as ThemeName | 'system')}>
                <Chip
                  label={t === 'system' ? 'Систем' : t === 'dark' ? 'Харанхуй' : 'Гэрэлтэй'}
                  tone={tweaks.theme === t ? 'accent' : 'neutral'}
                />
              </Pressable>
            ))}
          </Row>
        </Section>

        <Section title="Өнгөний өргөлт">
          <Row>
            {(['blue', 'teal', 'violet'] as AccentKey[]).map((a) => (
              <Pressable key={a} onPress={() => setTweak('accent', a)}>
                <Chip
                  label={a === 'blue' ? 'Цэнхэр' : a === 'teal' ? 'Тиал' : 'Ягаан'}
                  tone={tweaks.accent === a ? 'accent' : 'neutral'}
                />
              </Pressable>
            ))}
          </Row>
        </Section>

        <Section title="Булангийн радиус">
          <Row>
            {(['sharp', 'soft', 'pill'] as RadiusKey[]).map((r) => (
              <Pressable key={r} onPress={() => setTweak('radius', r)}>
                <Chip
                  label={r === 'sharp' ? 'Хатуу' : r === 'soft' ? 'Зөөлөн' : 'Бүтэн'}
                  tone={tweaks.radius === r ? 'accent' : 'neutral'}
                />
              </Pressable>
            ))}
          </Row>
        </Section>

        <Section title="Картын стиль">
          <Row>
            {(['flat', 'elevated', 'glass'] as CardKey[]).map((c) => (
              <Pressable key={c} onPress={() => setTweak('card', c)}>
                <Chip
                  label={c === 'flat' ? 'Хавтгай' : c === 'elevated' ? 'Сүүдэртэй' : 'Шилэн'}
                  tone={tweaks.card === c ? 'accent' : 'neutral'}
                />
              </Pressable>
            ))}
          </Row>
        </Section>

        <Button
          variant="danger"
          label="Гарах"
          onPress={() => {
            void logout();
            router.replace('/onboarding/role');
          }}
          style={{ marginTop: 24 }}
          leftIcon={<Feather name="log-out" size={16} color="#fff" />}
        />
      </View>
    </Screen>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={{ marginTop: 16 }}>
      <Text variant="eyebrow" tone="tertiary" style={{ marginBottom: 8 }}>
        {title}
      </Text>
      {children}
    </View>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <View style={styles.row}>{children}</View>;
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row', flexWrap: 'wrap', gap: 6 },
});
