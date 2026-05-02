/**
 * Business chat list — list of conversation threads keyed off the
 * `/v1/chat/threads` endpoint. Tapping a thread opens the same WS-backed
 * chat surface the driver uses (re-export from the driver folder).
 */

import { Feather } from '@expo/vector-icons';
import { useQuery } from '@tanstack/react-query';
import { useRouter } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import { listThreads } from '../../src/api/chat';
import { Empty, Loading } from '../../src/components/Empty';
import { Glass } from '../../src/components/Glass';
import { Screen } from '../../src/components/Screen';
import { ScreenHeader } from '../../src/components/ScreenHeader';
import { Text } from '../../src/components/Text';
import { relativeMn } from '../../src/lib/format';
import { useTheme } from '../../src/theme/ThemeProvider';

export default function BusinessChatList() {
  const theme = useTheme();
  const router = useRouter();
  const threadsQ = useQuery({ queryKey: ['chat', 'threads'], queryFn: () => listThreads() });
  const items = threadsQ.data?.items ?? [];

  return (
    <Screen scroll>
      <ScreenHeader sub="ЧАТ" title="Захиалгын яриа" />

      <View style={{ paddingHorizontal: 18 }}>
        {threadsQ.isLoading ? (
          <Loading />
        ) : items.length === 0 ? (
          <Empty
            title="Чат алга"
            sub="Захиалга хүлээж авмагц яриа автоматаар үүсэх ба энд харагдана."
          />
        ) : (
          <View style={{ gap: 10 }}>
            {items.map((t) => (
              <Pressable
                key={t.id}
                onPress={() =>
                  router.push({ pathname: '/(driver)/market/chat/[threadId]', params: { threadId: t.id } })
                }
              >
                <Glass radius="md">
                  <View style={{ flexDirection: 'row', alignItems: 'center', gap: 12 }}>
                    <View style={[styles.avatar, { backgroundColor: theme.colors.accent }]}>
                      <Feather name="user" size={18} color="#fff" />
                    </View>
                    <View style={{ flex: 1, minWidth: 0 }}>
                      <Text variant="body" weight="600" numberOfLines={1}>
                        Жолооч
                      </Text>
                      <Text variant="caption" tone="tertiary" numberOfLines={1}>
                        {t.last_message_at ? relativeMn(t.last_message_at) : 'Шинэ'}
                      </Text>
                    </View>
                    <Feather name="chevron-right" size={18} color={theme.colors.text3} />
                  </View>
                </Glass>
              </Pressable>
            ))}
          </View>
        )}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  avatar: {
    width: 40,
    height: 40,
    borderRadius: 20,
    alignItems: 'center',
    justifyContent: 'center',
  },
});
